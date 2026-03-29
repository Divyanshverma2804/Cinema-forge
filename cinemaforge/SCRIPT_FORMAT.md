# CinemaForge — Script Format Specification
# ═══════════════════════════════════════════════════════════════════
#
# The script is a PRODUCTION DOCUMENT.
# Every asset, voice, timing, and effect is declared here.
# The parser reads it, builds an asset manifest, and waits
# for all assets to be ready before a single frame renders.
#
# ═══════════════════════════════════════════════════════════════════

# ── PROJECT HEADER ──────────────────────────────────────────────────
# ProjectName: Suzy Lamplugh — Episode 1
# Type: narration               ← narration | dialogue | short | film
# Format: longform              ← longform | short | both
# Channels: EN, HI              ← which channels to post to
# AspectRatio: 9x16             ← 9x16 (shorts/vertical) | 16x9 (landscape)
# PageName: Dark Files          ← channel watermark name
# Tagline: true stories never told   ← outro tagline

# ── SCENE BLOCK ─────────────────────────────────────────────────────
# Each scene has:
#   - A name (used for asset folder matching)
#   - A background declaration: [STOCK] | [AI_IMAGE] | [AI_VIDEO] | [USER_VIDEO]
#   - Optional music/sfx declarations
#   - Optional speaker tag (for dialogue mode)
#   - The narration/dialogue lines

# ── BACKGROUND TYPES ────────────────────────────────────────────────
# [STOCK] dark London street fog              → auto-fetched from Pexels
# [AI_IMAGE] abandoned house cinematic zoom  → user generates + uploads
# [AI_VIDEO] foggy street slow push in       → user generates + uploads
# [USER_VIDEO] my_footage.mp4                → user uploads directly
#
# After [AI_IMAGE] or [AI_VIDEO] you can add a MOTION tag:
# zoom_in | zoom_out | pan_left | pan_right | still | ken_burns
# Example: [AI_IMAGE] police evidence board | zoom_in

# ── MUSIC DECLARATIONS ──────────────────────────────────────────────
# Music: dark_ambient             → looks in music/ folder for dark_ambient.mp3
# Music: continue                 → keep playing current track, no crossfade
# Music: none                     → silence for this scene
# Music: tension_swell            → special: auto-ramps volume at scene start

# ── SFX DECLARATIONS ────────────────────────────────────────────────
# SFX: none
# SFX: impact                     → sfx/impact.mp3 at scene start
# SFX: typewriter                 → sfx/typewriter.mp3 looped under narration
# SFX: thunder | 2.5              → sfx/thunder.mp3 at 2.5s into scene

# ── SPEAKER TAGS (dialogue mode only) ───────────────────────────────
# Speaker: Narrator [cold, slow]
# Speaker: Detective [gruff, urgent]
# Speaker: Witness [scared, quiet]
# Voice profiles are matched to Chatterbox voice refs in voices/ folder
# If no ref exists, Chatterbox uses the emotion params tuned to that profile

# ── SUBTITLE STYLE OVERRIDES ────────────────────────────────────────
# Style: hook        → word-by-word flash (like ReelForge hook)
# Style: punch       → full screen centered yellow
# Style: normal      → standard white caption (default)
# Style: none        → no subtitles for this scene

# ═══════════════════════════════════════════════════════════════════
# EXAMPLE 1 — TRUE CRIME NARRATION (longform)
# ═══════════════════════════════════════════════════════════════════

# ProjectName: Suzy Lamplugh — Episode 1
# Type: narration
# Format: both
# Channels: EN, HI
# AspectRatio: 9x16
# PageName: Dark Files
# Tagline: true stories never told

## Scene: cold_open
# Background: [AI_VIDEO] empty London street 1980s fog slow zoom in cinematic | zoom_in
# Music: dark_ambient
# SFX: none
# Style: hook

London. July 28th. 1986.
A Monday.

## Scene: victim_intro
# Background: [STOCK] estate agent office morning light window
# Music: continue
# SFX: none
# Style: normal

Suzy Lamplugh was twenty-five years old.
She was the kind of person you noticed when she walked into a room.
Not because she demanded it.
But because she carried herself like someone who believed every day was worth showing up for.

## Scene: diary_entry
# Background: [AI_IMAGE] open diary handwriting desk soft afternoon light | zoom_in
# Music: continue
# SFX: typewriter | 0.0
# Style: normal

At 12:30 in the afternoon, she wrote a single entry in her work diary.
Mr Kipper. 37 Shorrolds Road. 1pm.
No first name. No phone number. No address on file.
She picked up the keys.
She left the office.
She was never seen again.

## Scene: investigation
# Background: [AI_IMAGE] police evidence board photographs dark moody | still
# Music: tension_swell
# SFX: impact | 0.0
# Style: normal

The name Mr Kipper became the focal point of the entire investigation.
Police checked appointment books. Client records. Cold call logs.
No Mr Kipper existed anywhere in the agency's files.

## Scene: suspect
# Background: [STOCK] shadow man walking dark corridor
# Music: continue
# SFX: none
# Style: normal

The investigation quickly centred on a man named John Cannan.
Released from prison just three days before Suzy disappeared.
His nickname — given to him by women he had previously encountered — was Kipper.

## Scene: punch
# Background: [AI_IMAGE] single streetlight fog London night | still
# Music: continue
# SFX: none
# Style: punch

Forty years later. He has never said a word.

## Scene: outro_hook
# Background: [STOCK] dark corridor single light end
# Music: continue
# SFX: none
# Style: normal

Next time — we look at a case where the killer was identified within 48 hours.
The police had his name. His address. His photograph.
They filed the report. And then they did nothing.
For eleven years.
Subscribe. Because that story is coming.

---

# ═══════════════════════════════════════════════════════════════════
# EXAMPLE 2 — MOTIVATIONAL SHORT (same format as existing ReelForge)
# ═══════════════════════════════════════════════════════════════════

# ProjectName: calm_dominance
# Type: narration
# Format: short
# Channels: EN
# AspectRatio: 9x16
# PageName: Silenor
# Tagline: philosophy for the modern mind

## Scene: hook
# Background: [STOCK] dark forest fog morning light
# Music: dark_ambient
# SFX: none
# Style: hook

Stay calm when they expect you to react.

## Scene: conflict
# Background: [STOCK] storm waves crashing rocks
# Music: continue
# SFX: none
# Style: normal

Most people lose respect the moment they lose control.
Anger makes you loud.
But calm makes you dangerous.

## Scene: shift
# Background: [STOCK] calm water reflection mountain
# Music: continue
# SFX: none
# Style: normal

Real power is emotional discipline.
A calm mind sees what others miss.

## Scene: punch
# Background: [STOCK] lone figure mountain top sunrise
# Music: tension_swell
# SFX: impact | 0.0
# Style: punch

Calmness is silent dominance.

## Scene: engage
# Background: [STOCK] dark minimal background
# Music: continue
# SFX: none
# Style: normal

Type CALM if you feel this.

---

# ═══════════════════════════════════════════════════════════════════
# EXAMPLE 3 — DIALOGUE / FILM MODE
# ═══════════════════════════════════════════════════════════════════

# ProjectName: the_last_interview
# Type: dialogue
# Format: both
# Channels: EN
# AspectRatio: 9x16
# PageName: Dark Files
# Tagline: true stories never told

## Scene: opening
# Background: [AI_IMAGE] interrogation room harsh light single bulb | still
# Music: tense_ambient
# SFX: none
# Style: normal
# Speaker: Narrator [cold, slow]

The detective had one hour before the lawyer arrived.
He had one question.

## Scene: dialogue_1
# Background: [AI_IMAGE] interrogation room close up table | still
# Music: continue
# SFX: none
# Speaker: Detective [gruff, direct]

Where were you on the night of July 28th?

## Scene: dialogue_2
# Background: [AI_IMAGE] man in shadow close up | still
# Music: continue
# SFX: none
# Speaker: Suspect [calm, cold]

I was home. Alone. As always.

## Scene: dialogue_3
# Background: [AI_IMAGE] detective leaning forward interrogation | still
# Music: tension_swell
# SFX: none
# Speaker: Detective [gruff, direct]

Funny. Your neighbour saw your car leave at midnight.

## Scene: punch
# Background: [AI_IMAGE] close up hands on table | still
# Music: continue
# SFX: impact | 0.0
# Style: punch
# Speaker: Narrator [cold, slow]

Silence is not innocence.
