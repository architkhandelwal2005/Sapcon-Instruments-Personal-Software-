# Second run - testing what was fixed

The first run found six defects. Five are fixed and deployed. This run is built
to break them again if they are not really fixed, and to prove the rest still
works.

Everyone named here already exists from the first run, on purpose: the point is
that they are **linked**, not created a second time.

---

## Step 1 - the voice note (about a minute and a half)

Record and send. Talk normally, stumble, correct yourself.

> Right, quick recap of today. I went back to Parag Milk Foods, met Rajesh
> Sharma again. The four silo job is moving, he has got internal approval, and
> he wants the revised quotation with the radar transmitters by Thursday. Also
> he introduced me to their instrumentation engineer, a guy called Devang
> Bhatt, he will be doing the technical evaluation, so Sanjeevani should send
> him the datasheets this week.
>
> Then I spoke to Priya Nair at Holtec about the Ambuja job. She wants a
> reference list of cement plants where our radar transmitters are already
> installed. That is important, without it she will not shortlist us. Saurabh
> should put that list together by Friday.
>
> Also tell Vishal to call Rajesh on Monday to confirm the approval came
> through. And I think we should drop the Konkan Dairy follow-up for now,
> nothing is happening there.

### What to check

**People** - every one of these must say **linked**, not NEW:
Parag Milk Foods, Rajesh Sharma, Priya Nair, Holtec Consulting, Gujarat Ambuja.

**Devang Bhatt** is genuinely new, so NEW is correct for him.

**"tell Vishal to call Rajesh"** - a bare first name. It must link to **Rajesh
Sharma**, not create another Rajesh. *This is the fix from last time.*

**Tasks - four, with real dates**
1. Revised quotation to Parag - **Thursday's date**
2. Sanjeevani to send datasheets to Devang Bhatt - this week
3. Saurabh to build the reference list - **Friday's date**
4. Vishal to call Rajesh - **Monday's date**

**Not a task:** "drop the Konkan Dairy follow-up" is an instruction about an
existing lead, not new work. Either it drops the lead or it says it cannot find
it. A *task* called "drop the Konkan follow-up" would be wrong.

Then a **Confirm** button should arrive.

---

## Step 2 - corrections, as a NORMAL voice note

**Do not reply to the read-back.** Send this as a fresh voice note. That is the
whole point - last time this created a second meeting and changed nothing.

> Couple of corrections. The Parag quotation is due Wednesday, not Thursday.
> Saurabh should not do the reference list, give it to Vishal. And the datasheet
> task for Devang, nobody owns that yet, take Sanjeevani off it. Also the
> reference list is not just cement plants, it should be cement and steel.

### What to check

It must answer with **what it changed** - four lines - and a link. Not a
read-back. Not a new meeting.

Then open `/tasks` and confirm all four are really different:

| | |
|---|---|
| Parag quotation | due **Wednesday** |
| reference list | owner **Vishal**, text mentions **cement and steel** |
| datasheets for Devang | owner **nobody** |

If it files a new meeting instead, that fix did not work - tell me straight
away.

---

## Step 3 - a name correction, also as a normal message

> Devang's surname is Bhatt, not Bhat - Devang Bhatt with two t's

Should fix the record and link the wrong spelling as an alias. Only do this if
the read-back actually misspelled it; if it got it right, skip.

---

## Step 4 - questions, watching for displacement

Send these **one at a time**, waiting for each answer. Last time answers ran a
question behind.

| Send | Expect |
|---|---|
| `what's pending with Vishal` | His tasks including the reference list he just took over |
| `and Saurabh?` | **Saurabh's** work, not Vishal's. *This is the displacement fix* |
| `what happened at Parag Milk Foods` | Both visits, the approval, the Thursday/Wednesday quotation |
| `who is Devang Bhatt` | Instrumentation engineer at Parag, doing the technical evaluation |
| `what does Priya Nair want` | The reference list |
| `what is due this week` | Only genuinely dated items |
| `what is Devang's mobile number` | Must say it does not know. **Never invent** |

Then one misspelt on purpose:

| Send | Expect |
|---|---|
| `pending with Sanjivni` | "(Taking "sanjivni" as Sanjeevani.)" then her work |

---

## Step 5 - instructions

| Send | Expect |
|---|---|
| `give the abcd task to Vishal` | "No open task matches" - **and no new task created**. *This is the other fix* |
| `the Parag quotation is done` | Closed - check `/tasks` |
| `undo` | Reopened |
| `assign the reference list to Zaphod` | "Nobody on the team matches" |
| `drop Konkan Dairy` | Dropped, or a numbered choice if two match |

---

## What to send me

For each step: what came back, and whether `/tasks` agrees. The three that
matter most are the bare "Rajesh" linking, the corrections landing as changes
rather than a new meeting, and `and Saurabh?` answering about Saurabh.
