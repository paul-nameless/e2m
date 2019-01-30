# Email to maildir sync

Sync your emails to maildir (currently only imap supported)

## Getting started

There should be config file in the homedir `.email2maildir` with next format.

```
$ cat ~/.e2m-conf
[job]
email = [name]@[domain]
pswd = [password]
imap_host = imap.gmail.com
imap_port = 993
keep = 100
```

You can specify multiple sections with different accoutns.

Then add it to your crontab

```
*/2 * * * * /usr/local/bin/python3 $HOME/Documents/email2maildir/email2maildir.py 2>&1 >/dev/null
```
