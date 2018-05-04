#!/usr/bin/env python3
########################################################################
# File name: detach.py
# This file is part of: None
#
# LICENSE
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or (at
# your option) any later version.
#
# This program is distributed in the hope that it will be useful, but
# WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU
# General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
########################################################################
import base64
import quopri
import configparser
import smtplib
import email.header
import email.mime.multipart
import email.mime.text
import email.parser
import os
import subprocess
import shlex
import xdg.BaseDirectory
import re

from datetime import datetime


PREFIXTEXT = """\
NOTE: This is detach.py, sorry to interrupt you. I have taken
the attachments and put them into

    {destdir}

which can be accessed via

    {desturl}

for your convenience.
"""


def get_mails(maildir):
    for filename in os.listdir(maildir):
        parts = filename.split(",")
        if len(parts) == 1:
            # not a maildir file
            continue
        yield os.path.join(maildir, filename)


def exclude_seen_mails(mails):
    for filename in mails:
        parts = filename.split(",")
        if "S" in parts[-1]:
            # seen
            continue
        yield filename


def parse_mails(filenames):
    parser = email.parser.BytesParser()
    for filename in filenames:
        with open(filename, "rb") as fp:
            yield parser.parse(fp)


def filter_list_admin_mails(mails):
    for mail in mails:
        if not mail["X-List-Administrivia"]:
            continue
        yield mail


def filter_and_extract_nested_mails(mails):
    parser = email.parser.Parser()
    for mail in mails:
        payload = mail.get_payload()
        if not isinstance(payload, list):
            continue
        for part in payload:
            if part["Content-Type"] == "message/rfc822":
                yield mail, part.get_payload()[0]


def decode_header_string(hs):
    result = []
    for data, encoding in email.header.decode_header(hs):
        if isinstance(data, str):
            result.append(data)
        else:
            result.append(data.decode(encoding or "ascii"))
    return "".join(result)


def ask(prompt, options):
    options = list(map(str.lower, options))

    options_parts = [options[0].upper()]
    options_parts.extend(options[1:])
    options_str = "/".join(options_parts)

    while True:
        result = input(prompt.format(options_str))
        if not result:
            return options[0]
        if result.lower() in options:
            return result
        print("Incorrect choice")


def ask_nonexisting_dir(prompt, dirfmt, urlfmt):
    while True:
        destdir = input(prompt)
        full = dirfmt.format(destdir)
        fullurl = urlfmt.format(destdir)
        try:
            os.makedirs(full)
            return (full, fullurl)
        except FileExistsError:
            print("File exists, use a different path")


def find_attachments(parts):
    for part in parts:
        content_dispo = part["Content-Disposition"]
        if (content_dispo is not None and
            content_dispo.lower().startswith("attachment")):
            yield part


def extract_attachment_filename(part):
    return part.get_filename()


def decode_attachment(part):
    encoding = part["Content-Transfer-Encoding"]
    if encoding is None:
        return part.get_payload()

    encoding = encoding.strip()
    if encoding == "base64":
        return base64.b64decode(part.get_payload().encode("ascii"))
    elif encoding == "quoted-printable":
        return quopri.decodestring(part.get_payload().encode("ascii"))
    else:
        raise ValueError("Unknown transfer encoding: {}".format(encoding))


def process_mail(outer, inner, dir_pattern, url_pattern,
        recipient="fsr@ifsr.de", user="fsr-request"):
    TEXT_CONTENT_TYPES = {"text/html", "text/plain",
                          "application/html"}
    HEADERS_TO_TRANSFER = [
        "From",
        "Date",
        "Subject",
    ]

    attachments = []
    textual_data = []

    for attachment in find_attachments(inner.walk()):
        name = extract_attachment_filename(attachment)
        data = decode_attachment(attachment)
        attachments.append((name, data))

    for part in inner.walk():
        if part["Content-Type"] is None:
            continue
        ct = part["Content-Type"].split(";", 1)[0].strip()
        if ct.lower() in TEXT_CONTENT_TYPES:
            textual_data.append(part)

    new_message = email.mime.multipart.MIMEMultipart("mixed")

    if attachments:
        print("attachments have been found:")
        for i, (name, _) in enumerate(attachments):
            print("  [{}]: {}".format(i+1, name))

        dirfmt = datetime.utcnow().strftime(
            dir_pattern
        )
        urlfmt = datetime.utcnow().strftime(
            url_pattern
        )
        (destdir,desturl) = ask_nonexisting_dir(
            "attachment directory name (only suffix): ",
            dirfmt, urlfmt
        )
        os.chmod(destdir, 0o775)
        for name, data in attachments:
            path = os.path.join(destdir, name)
            with open(path, "wb") as f:
                f.write(data)
            os.chmod(path, 0o664)

        note = email.mime.text.MIMEText(
            PREFIXTEXT.format(destdir=destdir,desturl=desturl)
        )
        new_message.attach(note)

    textual_part = email.mime.multipart.MIMEMultipart("alternative")
    for data in textual_data:
        # hack to work around weird muas adding empty plaintext parts
        if data.get_payload().strip():
            textual_part.attach(data)

    new_message.attach(textual_part)

    for headername in HEADERS_TO_TRANSFER:
        if user != "fsr-request" and headername == "From":
            new_message[headername] = user + "@ifsr.de"
        else:
            new_message[headername] = inner[headername]

    new_message["To"] = recipient
    new_message["User-Agent"] = "detach.py/0.1"

    old_message_id = inner["Message-ID"].strip("<>")

    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")

    new_message["Message-ID"] = "<detached_at_{}_from_{}>".format(
        timestamp,
        old_message_id)

    return new_message


def learn_message(message, command):
    print()
    proc = subprocess.Popen(
        command,
        stdin=subprocess.PIPE
    )
    proc.communicate(message.as_bytes())
    if proc.wait() != 0:
        print("spam learn command failed.")
        print()


def get_smtp_conn(host, port, verbose):
    if verbose:
        print("connecting to {}:{}".format(host, port))
    conn = smtplib.SMTP(host, port)
    conn.starttls()
    conn.ehlo_or_helo_if_needed()
    return conn


def run(user, maildir, smtp_conn, exclude_seen, dir_pattern, url_pattern, learn_spam, learn_ham):
    mails = get_mails(maildir)
    if exclude_seen:
        mails = exclude_seen_mails(mails)

    parsed_mails = parse_mails(mails)
    list_admin_mails = filter_list_admin_mails(parsed_mails)
    mails_with_nested_mails = filter_and_extract_nested_mails(list_admin_mails)

    options = ["y", "n"]
    if learn_spam:
        options.append("s")

    # confirm id pattern
    pattern = re.compile("confirm\s\w{40}")

    for parsed, nested in mails_with_nested_mails:
        if not pattern.match(decode_header_string(nested["Subject"])):
            print("found matching mail:")
            print("  Subject: {}".format(
                decode_header_string(parsed["Subject"])
            ))
            print("  nested Subject: {}".format(
                decode_header_string(nested["Subject"])
            ))
            action = ask("Process mail? (Y = yes, n = no, s = learn as spam) [{}]", options)
            if action == "y":
                mail_to_send = process_mail(
                    parsed, nested, dir_pattern, url_pattern,
                )
                learn_message(nested, learn_ham)
            elif action == "s":
                learn_message(nested, learn_spam)
        else:
            print()
            action = ask("Reject mail for mailman? (Y = yes, n = no) [{}]", ["y", "n"])
            if action == "y":
                mail_to_send = process_mail(
                        parsed, nested, dir_pattern, url_pattern,
                        "fsr-request@ifsr.de", user
                )
        if action == "y":
            try:
                smtp_conn.send_message(mail_to_send)
            except smtplib.SMTPSenderRefused as err:
                smtp_conn = get_smtp_conn(smtp_host, smtp_port, args.verbose)
                smtp_conn.send_message(mail_to_send)



if __name__ == "__main__":
    import argparse
    import sys

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config", "-c",
        help="Configuration file to use, in addition to system- and user-wide"
        " configuration",
        default=None
    )

    parser.add_argument(
        "--with-read",
        dest="exclude_seen",
        action="store_false",
        default=True,
        help="Exclude messages marked as read (seen) "
        "(overrides value obtained from configuration)"
    )

    parser.add_argument(
        "-m", "--maildir",
        help="Path to maildir (overrides value obtained from configuration)",
        default=None,
    )

    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        dest="verbose",
        help="Be more verbose"
    )

    args = parser.parse_args()

    cfg = configparser.RawConfigParser()

    config_paths = list(xdg.BaseDirectory.load_config_paths("detach.ini"))
    config_paths.reverse()
    if args.config:
        config_paths.append(args.config)

    cfg.read(config_paths)

    if args.maildir:
        cfg.set("detach", "maildir", args.maildir)

    if not args.exclude_seen:
        cfg.set("detach", "exclude-seen", "false")

    try:
        user = cfg.get("detach", "user")
        maildir = cfg.get("detach", "maildir")
        exclude_seen = cfg.get("detach", "exclude-seen", fallback=True)
        smtp_host = cfg.get("smtp", "host", fallback="localhost")
        smtp_port = cfg.getint("smtp", "port", fallback=25)
        pattern = cfg.get("detach", "pattern")
        dir_pattern = cfg.get("detach", "dir")+pattern
        url_pattern = cfg.get("detach", "url")+pattern
        learn_spam = cfg.get(
            "spam", "learn-spam",
            fallback=None)
        if learn_spam is not None:
            learn_spam = shlex.split(learn_spam)
        learn_ham = cfg.get(
            "spam", "learn-ham",
            fallback=None)
        if learn_ham is not None:
            learn_ham = shlex.split(learn_ham)
    except (configparser.NoOptionError,
            configparser.NoSectionError,
            ValueError) as e:
        print("configuration error:", str(e))
        sys.exit(2)

    if args.verbose:
        print("looking in mailbox: {}".format(maildir))
        print("attachment directory pattern: {}".format(dir_pattern))
        print("using spam learn argv: {}".format(learn_spam))
        print("using ham learn argv: {}".format(learn_ham))

    conn = get_smtp_conn(smtp_host, smtp_port, args.verbose)
    try:
        run(user, maildir, conn, exclude_seen, dir_pattern, url_pattern, learn_spam, learn_ham)
    finally:
        conn.close()
