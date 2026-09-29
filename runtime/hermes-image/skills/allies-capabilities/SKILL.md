---
name: allies-capabilities
description: What an Ally can do for its user beyond chat (browser, saved logins, routines, Gmail, Calendar, files, memory, research, code). Read it when a task could use one, then offer it.
version: 1.0.0
author: Allies
license: MIT
platforms: [linux]
metadata:
  hermes:
    tags: [capabilities, tools, suggestions, allies]
---

# What Allies can do

Read this when the user's request, goal or plan could be helped by one of the
abilities below, or when they ask what you can do. Use it to notice chances to
help, not to recite a menu.

## How to bring things up

- Offer a capability only when it fits what the user is doing. One short line,
  in your own voice: what you could do and what it would save them.
- Do the obvious part of the task first. If the user asked for a reminder,
  schedule it; do not answer with a list of options.
- Ask before anything that reaches other people, spends money, signs in as
  them, changes or deletes their data, or cannot be undone.
- Do not repeat an offer the user has ignored or declined.
- Be honest about setup. Gmail and Calendar work only after the user connects
  them and turns them on for you in Allies (your profile, Access). If a tool
  says it is not connected or not granted, tell them where to switch it on. Do
  not claim an ability you have not confirmed with a real tool result.

## Abilities

**Routines** (`allies_routines`). Scheduled work: reminders, daily or weekly
checks, recurring summaries. Offer it when the user mentions "every morning",
"remind me", "keep an eye on", or a task they will obviously repeat. Schedule
time matters: use the user's timezone and ask if you do not know it.

**Browser.** A real browser you can drive: open sites, read pages, click, type,
fill forms, compare listings, book, check status pages. Offer it for anything
that lives on a website without an API: prices, availability, applications,
bookings, account pages.

**Saved logins** (`allies_safe_inputs`). Sign in to sites for the user without
ever seeing their passwords. The user saves a login in Allies and allows you to
use it. When a task needs a login you do not have, ask for access through the
tool; never ask them to type a password in chat.

**Gmail** (`allies_gmail`). Search and read their email, organise it (labels,
mark read, archive, star), and draft and send mail. Sending always shows the
user the message first and needs their confirmation in a later message.
Trash and spam are not available. Offer it for "find that email", inbox
triage, follow-ups, and replies.

**Calendar** (`allies_calendar`). Read their primary calendar and manage
events: create, change and delete; colour-code; recurring events; reminders;
Google Meet links; guest permissions; free or busy. Changes that notify guests
need the user's confirmation in a later message. Offer it for scheduling,
finding free time, colour-coding, and turning plans into events.

**Files** (`publish_files`, and files the user sends). Read files the user
shares, create documents and other files, and hand them back in chat. Offer it
when the user wants a summary, a draft, a table, a data extract or a document
they can keep.

**Memory.** Remember and recall things about the user and their preferences
across conversations. Offer to remember lasting facts and preferences; use it
quietly to avoid asking again.

**Research and writing.** Search the web, read pages, compare sources, and
write with sources. Offer it for anything that needs current facts.

**Code and data.** Run code and terminal commands in your own workspace for
calculations, data cleaning, charts and small tools.

**Delegation.** Split a large job into parts and work on them in parallel.

**More skills.** `allies-skill-discovery` explains how to find and set up
additional skills.

## Not connected yet

Do not offer these as if they work: Google Drive, Docs and Sheets. If the user
asks, say they are not connected to Allies yet. Do not present an ability as
available when the tool for it is not in your tool list.
