import configparser
import imaplib
import logging
import logging.handlers
import os
import socket
import time

home_dir = os.path.expanduser("~")
mail_dir = os.path.join(home_dir, 'mail')

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
logger = logging.getLogger(__name__)

hostname = socket.gethostname()
tmp_dir = os.path.join(mail_dir, 'tmp')
new_dir = os.path.join(mail_dir, 'new')
cur_dir = os.path.join(mail_dir, 'cur')


def get_tmp_filename():
    return f'{time.time()}-{os.getpid()}-{hostname}'


def notify(unseen):
    title, message = 'Gmail', f'Unread messages {unseen}'
    t = '-title {!r}'.format(title)
    m = '-message {!r}'.format(message)
    os.system(
        '/usr/local/bin/terminal-notifier -sound default {}'.format(
            ' '.join([m, t])
        )
    )


def truncate(conf):
    files = [e for e in os.listdir(cur_dir) if conf['email'] in e]
    logger.debug('Before deleting: %s', len(files))
    files.sort(key=lambda fn: int(fn.replace(conf['email'], '').split(':')[0]))
    for fn in reversed(files[int(conf['keep']):]):
        logger.debug('Deleting: %s', fn)
        os.remove(os.path.join(cur_dir, fn))
    logger.debug(
        'After deleting: %s',
        len([e for e in os.listdir(cur_dir) if conf['email'] in e])
    )


def sync(conf, section):
    state_file = os.path.join(mail_dir, f'.last-uid-{section}')
    last_saved_uid = None
    if os.path.isfile(state_file):
        with open(state_file) as f:
            content = f.read()
            if content.isdigit():
                last_saved_uid = int(content)

    mail = imaplib.IMAP4_SSL(conf['imap_host'], conf['imap_port'])
    mail.login(conf['email'], conf['pswd'])
    rc, data = mail.select('inbox', readonly=True)
    if rc != 'OK':
        logger.error('mail.select returned not ok response')
        return

    last_uid_str = data[0].decode()
    if not last_uid_str.isdigit():
        logger.error('last returned uid not digit: %s', last_uid_str)
        return
    last_uid = int(last_uid_str)

    if last_saved_uid:
        if last_uid <= last_saved_uid:
            logger.info(
                'No messages to retrieve: last_uid=%s, last_saved_uid=%s',
                last_uid, last_saved_uid
            )
            truncate(conf)
            return
        else:
            notify(last_uid-last_saved_uid)
            start_uid = last_saved_uid
    else:
        start_uid = last_uid - int(conf['keep'])

    for uid in range(start_uid, last_uid+1):
        _, mail_data = mail.fetch(str(uid).encode(), '(RFC822)')
        email = mail_data[0][1]
        tmp_path = os.path.join(tmp_dir, get_tmp_filename())
        with open(tmp_path, 'wb') as f:
            f.write(email)

        filename = f'{conf["email"]}-{uid}'
        os.rename(tmp_path, os.path.join(new_dir, filename))
        logger.debug('Synced: %s', filename)

    mail.close()

    with open(state_file, 'w') as f:
        f.write(str(last_uid))
        logger.debug('Saved last uid: %s', last_uid)
    truncate(conf)


lock_file = os.path.join('/tmp', 'eamil2maildir.pid')


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
                logger.info('Another instance running with pid: %s', pid)
                raise SystemExit
            else:
                logger.info('There is zombie file left from pid: %s', pid)
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
        conf = configparser.ConfigParser()
        conf.read(os.path.join(home_dir, '.e2m-conf'))
        for section in conf.sections():
            sync(conf[section], section)
    finally:
        release()


if __name__ == '__main__':
    main()
