# The test voice note, and what to send after it

Read part 1 aloud as a single WhatsApp voice note, at a normal speaking pace,
the way you would actually tell somebody about a day out. Do not read it
carefully - stumble, say "uh", correct yourself. That is the real input.

Then send the corrections in part 2, one at a time, **as replies to the
read-back message**, and check each one on the website before sending the next.

Everything here is invented. None of these people or orders are real.

---

## Part 1 - the voice note (about two and a half minutes)

> Okay so today was a long day, let me just recap everything before I forget.
> Morning I went to Parag Milk Foods in Manchar, met Rajesh Sharma, he is the
> maintenance head there. They are expanding the Manchar plant, putting in four
> new milk silos, and they need level transmitters for all four. He was asking
> specifically about radar type, not the guided wave ones, because last time
> they had some foam issue with the guided wave. I told him we will send a
> proper technical proposal. He wants the quotation by Friday, latest. Also
> Rajesh said their purchase head is a guy called Marmik Sapovadia, and any
> order above fifteen lakhs has to go through him, so we should copy him on
> everything. I did not get Marmik's number, I will have to ask Rajesh for it.
>
> After that I went to Gujarat Ambuja in Indore, met Anil Mehta, project
> engineer. This one is a bigger opportunity, the cement plant expansion. They
> need level measurement across the whole raw material handling section, maybe
> eight or ten points. Anil said the consultant on this is Holtec, and the
> Holtec person handling it is Priya Nair. We already know Priya, she was the
> one on the Konkan Dairy job last year. Anil wants us to go through Holtec, so
> Priya has to be convinced first, otherwise nothing will move. I think Vishal
> should handle Priya directly because they have spoken before. Tell Vishal to
> call her on Monday.
>
> Then in the evening I had a call with Konkan Dairy, the purchase person there.
> Nothing major, they were just asking about warranty terms on the transmitters
> we supplied last year. I told them standard is eighteen months from
> despatch. They may come back with a small order for two more units but nothing
> confirmed, so do not count it yet.
>
> Do teen aur cheezein hain. Sanjeevani ko bolo ki woh Parag ka quotation
> banaye, technical specs main Rajesh se le lunga. Saurabh should follow up with
> Anil Mehta after two weeks, just to keep it warm. And somebody needs to send
> the Holtec company profile to Priya Nair before Monday, otherwise Vishal's
> call will be a waste.
>
> One more thing, I am thinking we should target twenty five lakhs from the
> dairy segment this quarter. Parag alone could be fifteen if it comes through.
> Let us discuss in the Monday review.

---

## What the read-back should show

Check each of these. A miss is worth reporting; a wrong link is worth reporting
loudly.

**People and companies**
- Rajesh Sharma **linked** to the existing record, marked `!`
- Parag Milk Foods linked, not created again - it is now the correct spelling
- Marmik Sapovadia linked - he was merged from two records earlier
- Priya Nair, Anil Mehta, Gujarat Ambuja, Konkan Dairy, Holtec all linked
- Vishal, Sanjeevani, Saurabh recognised as staff, tagged `(our team)`

**Tasks - five, with the right owners and dates**
1. Send Parag Milk Foods a quotation - **due Friday's actual date**
2. Get Marmik Sapovadia's number from Rajesh - no date
3. Vishal to call Priya Nair - **Monday's actual date**
4. Sanjeevani to prepare the Parag quotation
5. Saurabh to follow up with Anil Mehta - **two weeks out**
6. Send the Holtec company profile to Priya - **before Monday**

**Decisions**
- Twenty-five lakh target for the dairy segment this quarter

**Should NOT appear**
- Any task about Konkan Dairy's possible two-unit order. You said do not count
  it yet. If a task appears for it, that is the system inventing commitment.

**Also check**
- The Hindi paragraph is understood. Sanjeevani's task must be there.
- A **Confirm** button arrives after the read-back.

---

## Part 2 - corrections, as replies to the read-back

Send these one at a time. Each tests a different path.

| # | Send | Should happen |
|---|---|---|
| 1 | "Rajesh is not the maintenance head, he is the projects head" | The connection is reworded |
| 2 | "the Konkan warranty thing is not a task, remove it" | Only if one was wrongly created. Otherwise it should say it cannot find it |
| 3 | "the Parag quotation is due Thursday not Friday" | Date changes on the website |
| 4 | "Saurabh should not follow up with Anil, give it to Vishal" | Owner changes |
| 5 | "nobody owns the Holtec profile task" | Owner removed |
| 6 | "it is Holtec Consulting, not just Holtec" | Name corrected, records merged if two exist |
| 7 | "also Anil mentioned their budget is around forty lakhs" | **Added** as new information, nothing changed |
| 8 | Tap **Confirm** | Everything settles, one reply naming what was confirmed |

After 3 and 4, open `/tasks` and confirm the change is really in the record -
not just in the reply.

---

## Part 3 - questions

Send as plain messages. No keyword.

| Send | Should come back |
|---|---|
| `what is pending with Vishal` | The Priya call, and whatever moved to him in part 2 |
| `and Sanjeevani?` | Her Parag quotation task. **Tests memory of the last question** |
| `what happened at Parag Milk Foods` | The visit, the four silos, the radar requirement |
| `give me Rajesh Sharma's number` | The number, or a clear "I do not have one" |
| `brief me on Gujarat Ambuja` | Anil, the expansion, Holtec, Priya, what is open |
| `how does Priya Nair connect to Gujarat Ambuja` | Through Holtec as consultant |
| `what is due this week` | Only genuinely dated items |
| `whats pending with Marmik` | Correct answer for the merged record |
| `what did Rajesh say about guided wave` | The foam problem, from the transcript |
| `what is Rajesh's wife's name` | It must say it does not know. **Tests that it will not invent** |

Misspell two on purpose:

| Send | Should come back |
|---|---|
| `pending with Vishaal` | "(Taking "vishaal" as Vishal Dixit.)" then the answer |
| `brief me on Pragmet` | "(Taking "pragmet" as Parag Milk Foods.)" then the answer |

---

## Part 4 - instructions

| Send | Should happen |
|---|---|
| `assign the Holtec profile task to Sanjeevani` | Applied, or a numbered choice |
| `the Parag quotation is done` | Task closed - check `/tasks` |
| `undo` | Reversed |
| `drop the Konkan Dairy lead` | Dropped, not deleted |
| `give the xyz task to Vishal` | "No open task matches", nothing changed |
| `assign the Priya task to Ramesh` | "Nobody on the team matches" |

---

## Part 5 - conversation

| Send | Should happen |
|---|---|
| `hi` | Short description of what it does |
| `thanks` | Silence |
| `what can you do` | Plain answer |
| `hmm ok whatever` | Says it did not follow, with examples |

---

## What to write down

For each: what you sent, what came back, and **whether the website agrees**. The
failures worth reporting first are where the reply and the record disagree -
everything else is cosmetic next to that.
