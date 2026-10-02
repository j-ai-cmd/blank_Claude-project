---
name: instagram-post
description: Prepare one Instagram Reel post for owner approval — the show's account, the rendered MP4, the writer's caption and first comment. Used only by the office's poster (Post).
---

# Instagram post

You never write or edit words, and you never post by yourself. You package one post for the owner's click.

1. Inputs: one rendered MP4 (from that show's builder) and one `caption.md` (from that show's writer).
   Missing either → return `blocked`.
2. Account per show: sherlock → `@sherlock_teaches_ai`, jai → `@jaidhingra_`, football → the football account the
   owner names in your training file. Unknown account → `blocked`, ask.
3. Check before packaging: `media_inspect` the MP4 (vertical 1080×1920, has audio); caption under 2,200 characters;
   at most 5 hashtags; the `## First comment` section exists.
4. Write `post.json` (FIRST output):
   `{"account": "...", "video": "artifact://...", "caption": "<caption text exactly as written>",
     "first_comment": "...", "cover_seconds": 1.5}`
5. Add ONE `pending_actions` entry: `{"action": "social.publish", "params": <post.json>, "preview": "<account> · <first caption line>"}`.
   The owner approves it (G3); only then does the connector post it.
