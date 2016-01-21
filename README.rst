``detach.py``
=============

Configuration
-------------

The configuration file is in dead-simple INI-like file format::

    [detach]
    maildir=/path/to/maildir/.INBOX/foo
    with-read=false
    dir-pattern=/home/fsr/attachments/%Y/%Y%m%d_{}

The ``maildir`` setting configures where detach.py will look for mailman
moderation emails. Note that it does not recurse into sub-directories, so you
have to give the full path to the mailbox which contains those mails.

If ``with-read`` is true, then also read (``seen`` in IMAP jargon) mails will
be included in the search. This makes things considerably slower, as more mails
have to be processed. Only after the mail has been opened and parsed, detach.py
is able to determine whether it is a moderation notice from mailman or not. The
check whether the mail has been marked as read is quick (it is contained in the
file name), so it is preferable to pre-filter your mails using this setting.

``dir-pattern`` specifies where attachments will be saved. It is first passed
through ``strftime(2)`` and then all occurences of ``{}`` are replaced by a
name which is prompted from the user interactively.

Usage
-----

Call ``python3 detach.py`` and follow the instructions on the screen. If the
script does not produce any output, it has not found any mails matching the
criteria.

Otherwise, it will ask you for each mailman moderation notice it found whether
it shall process it further. If you agree, it will analyse the mail for
attachments and list them to you.

It then asks you for a folder name to use (see the ``Configuration`` section
for details) and stores the attachments in that folder. Afterwards, the
original mail is re-sent without attachments but with a plaintext part put in
front of the original content which indicates where the attachments can be
found.
