``detach.py``
=============

Configuration
-------------

The configuration file is in dead-simple INI-like file format::

    [detach]
    user=stuhlbein
    maildir=/path/to/maildir/.INBOX/foo
    with-read=false
    pattern=%Y/%Y%m%d_{}
    dir=/home/fsr/attachments/
    url=https://www.ifsr.de/attachments/

The ``maildir`` setting configures where detach.py will look for mailman
moderation emails. Note that it does not recurse into sub-directories, so you
have to give the full path to the mailbox which contains those mails.

If ``with-read`` is true, then also read (``seen`` in IMAP jargon) mails will
be included in the search. This makes things considerably slower, as more mails
have to be processed. Only after the mail has been opened and parsed, detach.py
is able to determine whether it is a moderation notice from mailman or not. The
check whether the mail has been marked as read is quick (it is contained in the
file name), so it is preferable to pre-filter your mails using this setting.

``pattern`` specifies where attachments will be saved. It is first passed
through ``strftime(2)`` and then all occurences of ``{}`` are replaced by a
name which is prompted from the user interactively.

The actual directory is built by prefixing the result of the ``pattern`` 
expansion with the ``dir`` setting. The mail also provides an URL where the
attachments can be reached. The base URL is configured by the ``url`` setting
and included in the mail with the expanded ``pattern`` appended to it.

In the optional ``[spam]`` section of the config file, commands which can be
used to train spam and ham can be configured. Those have no defaults.
Example for the ``sa-learn`` command::

  [spam]
  learn-spam=sa-learn --spam
  learn-ham=sa-learn --ham

The commands receive the message to learn on stdin. The options are in shell
syntax, i.e. to pass ``foo bar`` as one argument use ``command "foo bar"``. For
more infos on the exact syntax, see the
`shlex.split() Python documentation
<https://docs.python.org/3/library/shlex.html#shlex.split>`_.


Usage
-----

Call ``python3 detach.py`` and follow the instructions on the screen. If the
script does not produce any output, it has not found any mails matching the
criteria.

Otherwise, it will ask you for each mailman moderation notice it found whether
it shall process it further. If you agree, it will analyse the mail for
attachments and list them to you.

If ``learn-spam`` has been configured, a third option (``s``) is available. In
that case, the message is trained as spam and not processed otherwise.

It then asks you for a folder name to use (see the ``Configuration`` section
for details) and stores the attachments in that folder. Afterwards, the
original mail is re-sent without attachments but with a plaintext part put in
front of the original content which indicates where the attachments can be
found.
