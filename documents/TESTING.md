# Testing checklist

What to send, and what a correct answer looks like. Work down it; each section
stands alone, so a failure in one does not invalidate the rest.

Two numbers worth keeping in mind while testing:

- **A voice note costs about 4 AI calls**, a question about 2, a greeting none.
  The free allowance is 500 a day and resets around 12:30 PM IST. A full pass
  of this document is roughly 60 calls.
- **The first message after a quiet spell waits ~50 seconds** while the free
  server wakes up. That is not a fault.

Check every result in two places: **the reply on WhatsApp**, and **the row on
the website**. A reply that reads well over a record that is wrong is the
failure mode this whole system exists to prevent.

---

## 1. Voice notes - the main path

### 1.1 A plain field visit
> "Met Rajesh Sharma at Parag Milk Foods in Manchar today. They need two radar
> level transmitters for the milk silos. He asked for a quotation by Friday.
> Tell Vishal to follow up on Monday."

Check the readback: person, company and location all present; the task carries
**Friday's actual date**, not "in a few days"; "tell Vishal" is matched to
Vishal Dixit on the roster. Then open the meeting link and confirm the same
facts are in the record, not just in the message.

### 1.2 Names already in the system
Name three people the database already holds - Rakesh Sharma, Priya Nair,
Kanika Chadha - and a company it holds, like Konkan Dairy Products.

The point is spelling. They should come back exactly right and be **linked**,
not created again. A line marked `!` with `"heard" -> Existing Name` means it
linked - which is the outcome to check hardest, because a wrong link merges two
customers' histories and cannot be cleanly undone.

### 1.3 A name it has never heard
Invent one: "Met Suhas Deshpande at Bharat Agro Foods."

It should create them as new, not force them onto an existing name. Then check
`/contacts` for a near-miss that should have been flagged and was not.

### 1.4 Hindi mixed in
> "Aaj Parag Foods gaya tha. Unko do level transmitters chahiye. Vishal ko
> bolo Monday ko follow up kare."

The transcript may stay in Hindi - that is fine. What must work is the
extraction: the company, the requirement, and the task for Vishal.

### 1.5 An internal meeting, not a visit
> "Internal review today. Present were Vishal, Sanjeevani and Saurabh. We set
> the target at 25 calls a day for Maharashtra. Saurabh will handle the
> enquiries backlog."

This should be recorded as an **internal** meeting with attendees and a
decision, not as a customer visit. Check `/meetings` shows it as internal.

### 1.6 One person, several companies
> "Long day. Morning at Gujarat Ambuja with Anil Mehta, they want a quotation.
> Then Reliance Cement, met Rakesh, he will send the scope document. Evening
> call with Priya Nair about Konkan Dairy."

Three companies, three people, three separate follow-ups - none merged into one
another.

### 1.7 Dates said the way people say them
Use "next Tuesday", "end of the month", "in two weeks", "day after tomorrow" in
one note. Every task should carry a **real date**, and an undated one is better
than a wrong one. Check them on `/tasks`.

### 1.8 A vague note
> "Had a decent chat with the Konkan people. Nothing concrete yet."

Correct behaviour is to record little and invent nothing. No task, no
requirement, no invented next step.

### 1.9 A long note
Talk for two or three minutes about several visits. Check the readback stays
readable, lines marked `!` are not dropped, and the link is the last line.

### 1.10 A noisy one
Record in a car or on a street. Either it transcribes, or it says it could not
make out the speech. It must never invent content.

### 1.11 Reply to a readback to add something
Reply **to the readback message itself**: "Also he asked for the datasheet."

It should attach to that same meeting, not create a new one. Confirm on
`/meetings` that no second meeting appeared.

> Known limit: replying **adds**. It cannot unpick a wrong link or delete a
> wrong task - use the website for that.

---

## 2. Questions

Send these as plain messages, no keyword needed.

| Send | Expect |
|---|---|
| `what's pending with Vishal` | His open tasks, with dates. Nothing about anyone else |
| `give me Rajesh Sharma's number` | The number from the contact record, or a clear "I do not have one" |
| `brief me on Gujarat Ambuja` | Who, what was discussed, what is open |
| `what happened at Parag Foods` | The visit, from the transcript |
| `what's left` | Open work, grouped, urgent first - **not** the same item twice |
| `and Konkan?` *(straight after)* | The same question about Konkan. This tests memory |
| `who is Priya Nair` | Her record and how she came up |
| `what did I say about radar transmitters` | Pulled from transcripts |
| `how does Rakesh connect to Reliance Cement` | The relationship, explained |
| `what is overdue` | Only genuinely overdue tasks |

Check each answer for: no `[F1]`-style markers, nothing listed twice, and every
claim traceable to a real record. Ask something it cannot know - "what is
Rajesh's wife's name" - and confirm it says so rather than inventing.

---

## 3. Instructions

| Send | Expect |
|---|---|
| `assign the Rakesh follow-up to Vishal` | Applied, or a numbered choice if two match |
| `2` *(replying to that choice)* | Applies to that one only |
| `undo` *(replying to the confirmation)* | Owner restored. Check `/tasks` |
| `the Parag quotation is done` | Task closed. Verify on `/tasks` |
| `drop Meghmani` | Lead dropped, **not deleted** - still visible filtered by dropped |
| `give the xyz task to Vishal` | "No open task matches", and **nothing changed** |
| `assign the Rakesh task to Zaphod` | "Nobody on the team matches" |
| `tell Vishal to call Rajesh on Monday` | A **new task**, not a reassignment. This is a note, not an instruction |

The one that matters most: an instruction matching two rows must change
**neither** until you pick.

---

## 4. Conversation

| Send | Expect |
|---|---|
| `hi` | A short answer saying what it does |
| `thanks` | Silence. Correct - answering invites another "ok" |
| `what can you do` | A plain description |
| `ok` / 👍 | Silence |
| something meaningless | It says it did not follow, and gives examples |

---

## 5. Photos - never tested end to end

Send a **visiting card photo**. Then a **diary page** with the caption
containing the word `diary`.

Check the reply names a count, and `/review/capture/{id}` shows the photo beside
each extracted item, with the circled initials matched to the right employee -
or left unassigned rather than guessed.

Expect problems here. This is the least proven path.

---

## 6. The website

**As you (owner)** - https://sapcon-instruments-personal-software.onrender.com

- `/review` - confirm, edit and reject an item; a rejected one disappears from
  listings but is not deleted
- **The 36 duplicate flags** - the highest-value review work. Each is "these
  may be the same person"; a wrong merge cannot be cleanly undone
- `/contacts` - search, filter, and **fix a misheard name**. Do `Pragmet Foods`
  → `Parag Milk Foods`. Every voice note after that gets the spelling right
- `/tasks` - filter, reassign with the owner dropdown, mark done
- `/leads` - drop one, then find it again with the dropped filter
- `/meetings` - field visits and internal meetings both listed
- `/admin/users` - add an employee

**As an employee** - register on another phone with the number you added

- They see only their own tasks and leads
- `/contacts`, `/meetings`, `/ask`, `/review` are refused
- A lead that is not theirs returns "not found", not "not allowed"
- Editing the URL to another person's id changes nothing

---

## 7. Things that should fail well

- **Send from a number that is not registered** - silence, and nothing written
- **Send a document or a sticker** - a polite "not supported yet"
- **Send two voice notes back to back** - both processed, neither lost
- **Send while the AI service is refusing** - the reply must say the note is
  kept, and `scripts/retry_failures.py` must list it afterwards

---

## What to write down

For each test: what you sent, what came back, and whether the record matches.
The ones worth reporting are where **the reply and the record disagree** - that
is the failure this system is built to make impossible, and it is worth more
than a dozen cosmetic issues.
