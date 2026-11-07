# Publish to YouTube

RJClip writes your title, description, chapters and tags, and uploads with **your own** Google account. It's free: there's no RJClip server in the middle and nothing is sent anywhere until you press **Upload** and confirm. New uploads are **private** unless you choose otherwise.

> **Honest status:** the sign-in and upload code follows Google's documented OAuth and resumable-upload protocols and is tested against a fake Google server (including dropped connections, partial uploads and expired sign-ins). It has **not** yet been run against real YouTube from the development environment, so your first upload is its first real-world test. Use **Private** for that one.

## One-time setup (~5 minutes, free)

1. Go to **console.cloud.google.com** and create a project (any name, e.g. "RJClip").
2. **APIs & Services → Library**: search for **YouTube Data API v3** and click **Enable**.
3. **APIs & Services → OAuth consent screen**:
   - User type **External** → fill in an app name and your email.
   - On **Test users**, add **your own Google account** (the one that owns the channel).
   - You don't need to publish or verify the app; it's only for you.
4. **APIs & Services → Credentials → Create credentials → OAuth client ID**:
   - Application type: **Desktop app**.
   - **Download JSON.**
5. In RJClip: **Publish → Choose the client JSON file**, then **Connect YouTube**.
   - A Google sign-in tab opens. Pick your channel's account.
   - Google warns that the app isn't verified. That's expected for your own app: choose **Continue**.
   - Allow the two permissions: *manage your YouTube videos* (upload) and *view your YouTube account* (to show the channel name).
   - The tab says "YouTube connected"; close it.

## Using it

1. **Export** your video (Export page), and optionally make a thumbnail (Thumbnails page).
2. **Publish → Write it for me**:
   - Chapters come from the topics you talk about in the final edit.
   - You also get title ideas, a description and tags.
   - Edit anything.
   - With a free local AI (Ollama running), **Write with local AI** gives catchier wording.
3. Pick the export, the thumbnail and the visibility (**Private** / **Unlisted** / **Public**), or a **schedule**. Scheduled videos upload as private and go public at that time.
4. **Upload to YouTube**, then confirm.
   - The upload resumes by itself after network hiccups.
   - When it's done, the youtu.be link appears under *Uploaded*.

## Good to know

- **Limits:** Google gives each project 10,000 API units a day, and an upload costs about 1,600, so roughly **6 uploads per day**. Your channel also has YouTube's own daily upload limits.
- **Custom thumbnails** need a phone-verified channel. If it isn't verified, the video still uploads and RJClip says the thumbnail wasn't set.
- **Chapters** are written into the description (YouTube's format). YouTube needs the first one at 0:00, at least 3 of them, and each at least 10 seconds long; RJClip checks this.
- **Made for kids** is a legal requirement (COPPA). Answer it truthfully for every video.
- **Where your sign-in is kept:**
  - `<workspace>/secrets/youtube_token.json`, readable only by your user account.
  - It's never sent to the browser.
  - **Disconnect** revokes it with Google and deletes it.
- **Test users expire.** While your OAuth app is in "Testing", Google expires the sign-in after about 7 days. RJClip then says the sign-in expired; just press **Connect YouTube** again. (Moving the app "In production" avoids this, but Google may then ask for verification because uploading is a sensitive permission. Staying in Testing is simplest.)

## For developers

All Google endpoints can be overridden (used by the tests):

- `RJCLIP_GOOGLE_AUTH_URL`
- `RJCLIP_GOOGLE_TOKEN_URL`
- `RJCLIP_GOOGLE_REVOKE_URL`
- `RJCLIP_YOUTUBE_API_URL`
- `RJCLIP_YOUTUBE_UPLOAD_URL`

The code is in `backend/app/youtube.py`; tests are in `backend/tests/test_youtube.py` and `scripts/e2e_publish.py`.
