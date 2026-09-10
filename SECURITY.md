# Security Policy

WeChat AI Memory handles private local data. Security and privacy regressions
are treated as high-priority issues.

## Reporting

Use GitHub's private vulnerability reporting feature when it is enabled for
the repository. Do not open a public issue containing chat content, database
files, account identifiers, memory keys, screenshots with personal data, or
exported archives.

Include the application version, Windows and WeChat versions, reproduction
steps using synthetic data, and the expected security boundary.

## Data Boundary

The application is read-only with respect to WeChat data. Database and image
keys remain in process memory and are never written to disk.

Decrypted database copies, recovered images, extracted voice clips, and
rendered pages live only in per-session directories under the system temp
folder. They are deleted when the data source is closed, and directories left
behind by a crash are removed on the next start. The only chat-derived data
cached automatically is the text of voice transcripts, stored under
`%LOCALAPPDATA%\WeChatAIMemory` next to the downloaded speech model. Everything
else written to disk (PDF, Markdown, JSON, copied attachments, optional page
images) goes only to the locations the user selects for an export.

No telemetry or remote AI API is used. The only network access is the one-time
download of the local speech model; that request carries no chat data, Hub
usage reporting is disabled, and no locally cached Hugging Face token is
attached.
