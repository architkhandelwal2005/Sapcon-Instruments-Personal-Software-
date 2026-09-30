# Second run - harder, and aimed at what was fixed

The first run found six defects. Five are fixed and deployed. This note is
built to break them again if the fixes are not real, and to push harder than
the first: five companies, seven people, six different ways of saying a date, a
competitor, a handover between two contacts, an instruction in Hindi, and one
thing said in passing that must NOT become a task.

New people and companies are new on purpose. The ones carried over from the
first run - Rajesh Sharma, Parag, Priya Nair, Holtec, Gujarat Ambuja, Anil
Mehta, Marmik - must come back **linked**, never created again.

---

## Step 1 - the voice note (about two and a half minutes)

Record and send it. Talk normally. Stumble, repeat yourself, correct yourself
mid-sentence - that is the real input, and a cleanly read script tests nothing.

> Okay, long day, let me get everything down before I forget.
>
> Started at **Shreeji Agro Foods** in Baramati, met their plant head **Nilesh
> Kulkarni** and the maintenance in-charge, **Faisal Qureshi**. They are putting
> up a new edible oil refinery line, commissioning around March. They need level
> measurement on eight storage tanks, and two of those are for crude oil at about
> sixty degrees, so we will need the high temperature version. Nilesh was clear
> that they have already been quoted by **VEGA** and we are the second vendor, so
> pricing will matter. He wants a budgetary offer **in ten days**. **Sanjeevani**
> should prepare that.
>
> From there I went to **Mahalaxmi Sugar Mills** in Kolhapur. Met **Abhijeet
> Ranade**, he is the projects manager. Different situation, this is a retrofit -
> their existing radar units are failing in the molasses tanks because of the
> vapour. I have told him we will do a site visit before quoting. **Vishal**
> should go there **next Wednesday**, and he should take the demo unit with him.
>
> Then I called **Rajesh Sharma** at Parag, just to follow up. Approval has come
> through, the purchase order should be released by the **end of this month**. He
> also said their **Marmik** wants a compliance certificate before the PO, so
> somebody has to send that. **Saurabh** can do it, **by Friday**.
>
> **Priya Nair** from Holtec called me in the afternoon about the Gujarat Ambuja
> job. She has shortlisted three vendors and we are in. She wants a technical
> presentation **next Thursday** at their Delhi office. Vishal and I will both
> go. She also mentioned that **Anil Mehta** is being transferred and somebody
> called **Shwetha Iyer** will take over the project from him, so we need to
> build that relationship from scratch.
>
> Ek aur baat. **Deccan Ceramics** ne phir se enquiry bheji hai, lekin yeh log
> pichhle do saal se sirf pooch rahe hain, order kabhi nahi karte. Uska follow-up
> band kar do.
>
> Last thing, internal. I want us to close **forty lakhs this quarter** from the
> sugar and dairy segments together. Mahalaxmi alone could be twelve. Let us
> review on Monday.

### What to check in the read-back

**Linked, never created again**
Rajesh Sharma, Parag Milk Foods, Priya Nair, Holtec Consulting, Gujarat Ambuja,
Anil Mehta.

**"their Marmik"** - a bare first name. Must link to **Marmik Sapovadia**.
*This is last run's fix. If it creates a new Marmik, the fix is not real.*

**Genuinely new, so NEW is correct**
Shreeji Agro Foods, Nilesh Kulkarni, Faisal Qureshi, Mahalaxmi Sugar Mills,
Abhijeet Ranade, Shwetha Iyer, Deccan Ceramics.

**Hard names.** Kulkarni, Qureshi, Ranade, Shwetha Iyer. Note anything it
mangles - that is what the spelling correction in step 3 is for.

**Tasks - five, with real dates**

| Task | Owner | Due |
|---|---|---|
| Budgetary offer to Shreeji Agro | Sanjeevani | ten days out |
| Site visit to Mahalaxmi, with the demo unit | Vishal | next Wednesday |
| Compliance certificate to Parag | Saurabh | Friday |
| Technical presentation at Holtec Delhi | Vishal (and him) | next Thursday |
| Monday review | - | Monday |

**A decision** - forty lakhs this quarter from sugar and dairy.

**Should NOT be a task:** the Deccan Ceramics line is an instruction to stop
following up, not work to do. Either it drops that lead, or it says it cannot
find it. A task called "stop the Deccan follow-up" is wrong.

**Also should not appear:** anything committing to a purchase order. He said the
PO *should* be released - that is Parag's action, not ours.

Then a **Confirm** button.

---

## Step 2 - corrections, as a NORMAL voice note

**Do not reply to the read-back.** Send a fresh voice note. This is the fix that
failed last time, when the same thing created a second meeting and changed
nothing.

> Few corrections. The Shreeji budgetary offer, make it **fifteen days**, not
> ten. The Mahalaxmi site visit should be **Saurabh**, not Vishal, Vishal is
> tied up. The compliance certificate for Parag - **remove that**, Rajesh said
> he will get it from their own quality team. And the presentation is at
> Holtec's **Mumbai** office, not Delhi.

### What to check

It must answer with **what it changed** - four lines and a link. **Not a
read-back. Not a new meeting.**

Then open `/tasks` and confirm all four really moved:

| | |
|---|---|
| Shreeji budgetary offer | due **fifteen days out** |
| Mahalaxmi site visit | owner **Saurabh** |
| Compliance certificate | **gone** from the list |
| Presentation | text says **Mumbai** |

If a new meeting appears instead, stop and tell me.

---

## Step 3 - a spelling correction, also as a normal message

Only if the read-back actually got one wrong. Use whichever it mangled:

> It is Abhijeet Ranade, not whatever you wrote - A B H I J E E T

Should fix the record and keep the wrong spelling as an alias.

---

## Step 4 - questions, one at a time

Wait for each answer before sending the next.

| Send | Expect |
|---|---|
| `what's pending with Vishal` | The presentation. **Not** the Mahalaxmi visit - that moved to Saurabh |
| `and Saurabh?` | **Saurabh's** work. *This is the displacement fix* |
| `what happened at Mahalaxmi Sugar Mills` | The retrofit, the molasses tanks, the vapour problem |
| `who is Shwetha Iyer` | Taking over the Ambuja project from Anil Mehta |
| `who is replacing Anil Mehta` | Shwetha Iyer |
| `what does Priya Nair want` | The presentation, and that we are shortlisted |
| `why are we the second vendor at Shreeji` | VEGA quoted first |
| `what is due next week` | Only genuinely dated items |
| `what is Faisal Qureshi's number` | Must say it does not know. **Never invent** |

Two misspelt on purpose:

| Send | Expect |
|---|---|
| `pending with Sanjivni` | "(Taking "sanjivni" as Sanjeevani.)" then her work |
| `brief me on Mahalakshmi` | Should still find Mahalaxmi Sugar Mills |

---

## Step 5 - instructions

| Send | Expect |
|---|---|
| `give the pqrs task to Vishal` | "No open task matches" - **and no task created**. *The other fix* |
| `the Shreeji budgetary offer is done` | Closed - check `/tasks` |
| `undo` | Reopened |
| `assign the Mahalaxmi visit to Zaphod` | "Nobody on the team matches" |
| `drop Deccan Ceramics` | Dropped, or a numbered choice |

---

## The four results I most want

1. **"their Marmik"** linked to Marmik Sapovadia, not created
2. Step 2 landing as **changes**, not a new meeting
3. **`and Saurabh?`** answering about Saurabh
4. `give the pqrs task to Vishal` **refusing without inventing anything**

For everything else: what came back, and whether `/tasks` agrees with it.
