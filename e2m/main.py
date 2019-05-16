import configparser
import email
import imaplib
import logging
import logging.handlers
import os
import time
import uuid

home_dir = os.path.expanduser("~")

conf = configparser.ConfigParser()
conf.read(os.path.join(home_dir, '.e2mrc'))

mail_dir = conf['DEFAULT']['maildir']

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s %(message)s',
    handlers=[
        logging.handlers.RotatingFileHandler(
            os.path.join(mail_dir, 'sync.log'),
            backupCount=1,
            maxBytes=1024*256
        ),
        logging.StreamHandler()]
)
log = logging.getLogger(__name__)

tmp_dir = os.path.join(mail_dir, 'tmp')
new_dir = os.path.join(mail_dir, 'new')
cur_dir = os.path.join(mail_dir, 'cur')
lock_file = os.path.join('/tmp', 'eamil2maildir.pid')


def get_tmp_filename():
    return f'{time.time()}-{os.getpid()}-{uuid.uuid4().hex[:16]}'


def notify(unseen, _from, subject):
    msg = '-message {!r}'.format(subject)
    subtitle = '-subtitle {!r}'.format(_from)
    title = '-title {!r}'.format(f'Synced {unseen} new emails')
    sound = '-sound default'
    icon_path = os.path.join(os.path.dirname(__file__), 'e2m.png')
    icon = f'-appIcon {icon_path}'
    cmd = '/usr/local/bin/terminal-notifier'

    os.system(
        f'{cmd} {icon} {sound} {title} {subtitle} {msg}'
    )


def truncate(conf):
    files = [e for e in os.listdir(cur_dir) if conf['email'] in e]
    log.debug('Before deleting: %s', len(files))
    files.sort(key=lambda fn: int(fn.replace(conf['email'], '').split(':')[0]))
    for fn in reversed(files[int(conf['keep']):]):
        log.debug('Deleting: %s', fn)
        os.remove(os.path.join(cur_dir, fn))
    log.debug(
        'After deleting: %s',
        len([e for e in os.listdir(cur_dir) if conf['email'] in e])
    )


def initial_sync(conf):
    state_file = os.path.join(mail_dir, f'.last-uid-{conf["email"]}')
    mail = imaplib.IMAP4_SSL(conf['imap_host'], conf['imap_port'])
    mail.login(conf['email'], conf['pswd'])
    rc, data = mail.select('inbox', readonly=True)

    if rc != 'OK':
        log.error('mail.select returned not ok response')
        return
    last_uid_str = data[0].decode()

    if not last_uid_str.isdigit():
        log.error('last returned uid not digit: %s', last_uid_str)
        return
    last_uid = int(last_uid_str)
    start_uid = last_uid - int(conf['keep'])

    for uid in range(start_uid, last_uid+1):
        _, mail_data = mail.fetch(str(uid).encode(), '(RFC822)')
        email = mail_data[0][1]
        tmp_path = os.path.join(tmp_dir, get_tmp_filename())
        with open(tmp_path, 'wb') as f:
            f.write(email)

        filename = f'{conf["email"]}-{uid}:2,S'
        os.rename(tmp_path, os.path.join(cur_dir, filename))
        log.debug('Initial sync, marked as read: %s', filename)

    with open(state_file, 'w') as f:
        f.write(str(last_uid))
        log.debug('Saved last uid: %s', last_uid)

    mail.close()


def sync(conf):
    state_file = os.path.join(mail_dir, f'.last-uid-{conf["email"]}')
    last_saved_uid = None
    if os.path.isfile(state_file):
        with open(state_file) as f:
            content = f.read()
            if content.isdigit():
                last_saved_uid = int(content)
    if last_saved_uid is None:
        initial_sync(conf)
        return

    mail = imaplib.IMAP4_SSL(conf['imap_host'], conf['imap_port'])
    mail.login(conf['email'], conf['pswd'])
    rc, data = mail.select('inbox', readonly=True)
    if rc != 'OK':
        log.error('mail.select returned not ok response')
        return

    last_uid_str = data[0].decode()
    if not last_uid_str.isdigit():
        log.error('last returned uid not digit: %s', last_uid_str)
        return
    last_uid = int(last_uid_str)
    log.debug('Last uid: %s', last_uid)

    if last_uid <= last_saved_uid:
        log.info(
            'No messages to retrieve: last_uid=%s, last_saved_uid=%s',
            last_uid, last_saved_uid
        )
        truncate(conf)
        return
    else:
        start_uid = last_saved_uid

    last_email = None
    filters = conf.get('filters')
    for uid in range(start_uid+1, last_uid+1):
        _, mail_data = mail.fetch(str(uid).encode(), '(RFC822)')
        _email = mail_data[0][1]
        tmp_path = os.path.join(tmp_dir, get_tmp_filename())
        with open(tmp_path, 'wb') as f:
            f.write(_email)
        last_email = email.message_from_bytes(_email)

        filename = f'{conf["email"]}-{uid}'
        if filters and match_filter(last_email['subject'], filters):
            # filename += ':2,S'
            log.debug(
                'Marking email as read because of filter: %s', filename
            )
            last_email = None
            os.rename(tmp_path, os.path.join(cur_dir, filename))
            continue

        os.rename(tmp_path, os.path.join(new_dir, filename))
        log.debug('Synced: %s', filename)

    if last_email:
        notify(
            last_uid-last_saved_uid,
            last_email['from'],
            last_email['subject']
        )

    with open(state_file, 'w') as f:
        f.write(str(last_uid))
        log.debug('Saved last uid: %s', last_uid)
    truncate(conf)
    mail.close()


def match_filter(subject, filters):
    return any([
        key_phrase.strip() in subject
        for key_phrase in filters.split('|')
    ])


def pid_exists(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:   # errno.ESRCH
        return False  # No such process
    except PermissionError:  # errno.EPERM
        return True  # Operation not permitted (i.e., process exists)
    else:
        return True  # no error, we can send a signal to the process


def lock():
    if os.path.isfile(lock_file):
        with open(lock_file) as f:
            pid = int(f.read())
            if pid_exists(pid) and pid != os.getpid():
                log.info('Another instance running with pid: %s', pid)
                raise SystemExit
            else:
                log.info('There is zombie file left from pid: %s', pid)
                os.remove(lock_file)

    with open(lock_file, 'w') as f:
        f.write(str(os.getpid()))


def release():
    try:
        os.remove(lock_file)
    except FileNotFoundError:
        pass


def main():
    lock()
    try:
        for section in conf.sections():
            sync(conf[section])
    except Exception:
        log.exception('Error happened during sync')
    finally:
        release()


if __name__ == '__main__':
    main()
