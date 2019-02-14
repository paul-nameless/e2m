# Email to maildir sync

Sync your emails to maildir (currently only imap supported)


## Install

```
pip install e2m
```

## Getting started

Config file required in the homedir `.e2mrc` with next format.

```
$ cat ~/.e2mrc
[job]
email = [name]@[domain]
pswd = [password]
imap_host = imap.gmail.com
imap_port = 993
keep = 256
```

You can specify multiple sections with different accoutns.

Then add it to your crontab

```
*/2 * * * * /usr/local/bin/e2m 2>&1 >/dev/null
```
