#!/usr/bin/env python3
import base64
import smtplib
import email.header
import email.mime.multipart
import email.mime.text
import email.parser
import os

from datetime import datetime


PREFIXTEXT = """\
NOTE: This is detach.py, sorry to interrupt you. I have taken
the attachments and put them into

    {destdir}

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
                break


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


def ask_nonexisting_dir(prompt, dirfmt):
    while True:
        destdir = input(prompt)
        full = dirfmt.format(destdir)
        try:
            os.makedirs(full)
            return full
        except FileExistsError:
            print("File exists, use a different path")


def find_attachments(parts):
    for part in parts:
        content_dispo = part["Content-Disposition"]
        if (content_dispo is not None and
            content_dispo.lower().startswith("attachment")):
            yield part


def extract_attachment_filename(part):
    # normalize whitespace
    content_dispo = " ".join(part["Content-Disposition"].split())

    # XXX: this is not proper parsing... this should be fixed at some point
    options = content_dispo.split(";", 1)
    for option in options:
        option = option.strip()
        name, _, value = option.partition("=")
        if name == "filename":
            return decode_header_string(value).strip('"').replace("/", "_")
        elif name == "filename*":
            if value.startswith("UTF-8''"):
                value = value[7:]
            return decode_header_string(value).strip('"').replace("/", "_")

    return None


def decode_attachment(part):
    encoding = part["Content-Transfer-Encoding"]
    if encoding is None:
        return part.get_payload()

    encoding = encoding.strip()
    if encoding == "base64":
        return base64.b64decode(part.get_payload().encode("ascii"))
    else:
        raise ValueError("Unknown transfer encoding: {}".format(encoding))


def process_mail(outer, inner):
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
            "/home/fsr/attachments/%Y/%Y%m%d_{}"
        )
        destdir = ask_nonexisting_dir(
            "attachment directory name (only suffix): ",
            dirfmt
        )
        os.chmod(destdir, 0o775)
        for name, data in attachments:
            path = os.path.join(destdir, name)
            with open(path, "wb") as f:
                f.write(data)
            os.chmod(path, 0o664)

        note = email.mime.text.MIMEText(
            PREFIXTEXT.format(destdir=destdir)
        )
        new_message.attach(note)

    textual_part = email.mime.multipart.MIMEMultipart("alternative")
    for data in textual_data:
        # hack to work around weird muas adding empty plaintext parts
        if data.get_payload().strip():
            textual_part.attach(data)

    new_message.attach(textual_part)

    for headername in HEADERS_TO_TRANSFER:
        new_message[headername] = inner[headername]

    new_message["To"] = "fsr@ifsr.de"
    new_message["User-Agent"] = "detach.py/0.1"

    old_message_id = inner["Message-ID"].strip("<>")

    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S%f")

    new_message["Message-ID"] = "<detached_at_{}_from_{}>".format(
        timestamp,
        old_message_id)

    return new_message


def get_smtp_conn(__data={}):
    try:
        return __data["conn"]
    except KeyError:
        conn = smtplib.SMTP("localhost", 25)
        conn.starttls()
        __data["conn"] = conn
        return conn


def send_mail(mail):
    conn = get_smtp_conn()
    conn.send_message(mail)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--with-read",
        dest="exclude_seen",
        action="store_false",
        default=True,
        help="Exclude messages marked as read (seen)"
    )
    parser.add_argument(
        "maildir",
        help="Path to maildir"
    )

    args = parser.parse_args()

    mails = get_mails(args.maildir)
    if args.exclude_seen:
        mails = exclude_seen_mails(mails)

    parsed_mails = parse_mails(mails)
    list_admin_mails = filter_list_admin_mails(parsed_mails)
    mails_with_nested_mails = filter_and_extract_nested_mails(list_admin_mails)

    for parsed, nested in mails_with_nested_mails:
        print("found matching mail:")
        print("  Subject: {}".format(
            decode_header_string(parsed["Subject"])
        ))
        print("  nested Subject: {}".format(
            decode_header_string(nested["Subject"])
        ))

        if ask("Process mail? [{}]", ["y", "n"]) == "y":
            mail_to_send = process_mail(
                parsed, nested
            )

            send_mail(mail_to_send)
