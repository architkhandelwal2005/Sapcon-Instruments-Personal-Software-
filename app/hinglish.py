# -*- coding: utf-8 -*-
"""The Hindi words that carry no information about which record is meant.

Two places in this system take the words somebody used and work out which row
they meant: a question picks out what might be a name, and an instruction is
scored against the text of the tasks it might refer to. Both already knew to
ignore ordinary English - "how many calls did we make" once matched "make" to
ICE Make Refrigeration Limited. Neither knew any Hindi.

That was not symmetrical in its damage. A question mostly survived it, because
a Hindi word rarely looks like a customer. An instruction did not: scoring
counts how many of the meaningful words were found, and refuses a match below
sixty per cent of them. "Rajesh wala task band kar do" offers four meaningful
words, three of which are grammar that no English task description will ever
contain, so one honest hit on "rajesh" reads as a partial match and the
instruction is refused - while "Rajesh task" is carried out. He would be told
his own clear instruction was too vague to act on.

The two lists stay separate because they answer different questions: "could
this be a name" also rules out words like "quotation", which "which task did he
mean" very much needs. What they share is grammar, and grammar is what lives
here.

Romanised only. Devanagari never reaches these - by the time a word gets this
far it has been through a transcriber that is asked for Roman letters, and a
name in another script is held for review rather than matched (see
app/transcription/prompt.py and app/entity_resolution/resolve.py).

Over-inclusive on purpose, and the cost of that was measured rather than
assumed. Checked word by word against all 1,697 real contacts, exactly one
collides: "magar", the Hindi for "but" and the surname of Amol Magar. He says
"magar" constantly and asks about that one contact by bare surname approximately
never - and asking by full name is answered before this list is consulted at
all. ("bas" resembles BASF, but at three letters it is below the length a word
needs to be considered a name, so it never arrives.)

What that collision costs is a fuzzy lookup falling through to "I have
nothing", which is where an unrecognised name was going anyway. What it buys is
not answering confidently about the wrong person.
"""

FUNCTION_WORDS = frozenset({
    # being, doing, going
    "hai", "hain", "tha", "thi", "the", "hoga", "hogi", "honge", "hona", "hua",
    "hui", "hue", "raha", "rahi", "rahe", "gaya", "gayi", "gaye", "jana", "jaa",
    "karna", "karne", "karta", "karti", "karte", "karo", "kare", "karenge",
    "kiya", "kiye", "kar", "kardo", "kardiya",
    "bol", "bola", "bole", "boli", "bolo", "bolna", "bataya", "batao",
    "bhej", "bheja", "bheji", "bhejna", "bhejni", "bhejenge", "bhejo",
    "dena", "dena", "denge", "diya", "diye", "dedo", "dede", "do",
    "lena", "liya", "liye", "lo", "mila", "mili", "mile", "milna", "milenge",
    "chahiye", "chaiye", "sakta", "sakte", "sakti", "lagta", "lagti", "lagega",
    "rakho", "rakha", "dekho", "dekha", "dekhna", "suno", "suna",
    "aana", "aaya", "aayi", "aaye", "aao", "jayenge", "jayega",
    "pata", "chala", "chal", "samajh", "samjha", "pucha", "poocha",
    "laga", "lage", "lagi", "kaha", "kahe", "kahna", "mana",

    # who and whose
    "mera", "meri", "mere", "humara", "hamara", "humein", "hamein", "hum",
    "tumhara", "tumhari", "aapka", "aapki", "aapke", "aap", "tum",
    "uska", "uske", "uski", "unka", "unke", "unki", "iska", "iske", "iski",
    "inka", "inke", "apna", "apne", "apni", "woh", "yeh", "koi", "kuch",

    # glue
    "aur", "lekin", "magar", "kyunki", "kyun", "kaise", "kahan", "yahan",
    "wahan", "jahan", "phir", "abhi", "tabhi", "jab", "tab", "agar", "warna",
    "saath", "baad", "pehle", "andar", "bahar", "upar", "niche", "bina",
    "tak", "bhi", "hi", "par", "mein", "se", "ko", "ka", "ke", "ki", "na",
    "nahi", "nahin", "haan", "kya", "kitna", "kitne", "kitni",

    # degree and judgement
    "bilkul", "zaroor", "shayad", "matlab", "bahut", "thoda", "zyada", "sirf",
    "bas", "chalo", "waise", "aisa", "aise", "theek", "thik", "achha", "accha",
    "sahi", "pura", "poora", "sab", "sabhi", "ekdum",

    # what he does to a task or a lead
    "wala", "wali", "wale", "band", "chalu", "shuru", "khatam", "jaldi",
    "turant", "wapas", "dobara", "kaam", "baat", "baatein",

    # when
    "aaj", "kal", "parso", "subah", "shaam", "raat", "dopahar",
    "hafta", "hafte", "mahina", "mahine", "saal", "din", "agle", "pichle",
    "somvar", "somvaar", "somwar", "mangalwar", "budhwar", "guruwar",
    "shukrawar", "shaniwar", "ravivar", "itwar",
})
