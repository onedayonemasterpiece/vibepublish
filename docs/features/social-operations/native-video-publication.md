# Native MP4 publication

Status: Not confirmed by user. Implementation and real-provider verification in progress.

## Fixed requested outcome
An owner-approved MP4 must remain video when published to Telegram and VK wall, and when separately published as a native VK video Story. No photo substitution, browser publication, silent trimming, credential changes or permission expansion.

## Bounded implementation
Reuse the existing private resumable import_begin/chunk/finish protocol with mime video/mp4. Retain the 20 MiB/120 second H.264/AAC local safety bounds, full decode validation, sanitized container derivative, quota, immutable asset digest and atomic upload completion. Existing image commands remain compatible.

Telegram uses uploaded document media with DocumentAttributeVideo and supports_streaming, not a generic downloadable file. VK wall uses video.save(wallpost=0), multipart video_file, exact video.get identity/processing observation, then wall.post with that native video attachment. The first video allocation is inside the durable dispatch boundary. Uncertain allocation/upload/processing must not be retried as a new video. Existing exact wall receipt reconciliation stays authoritative.

VK Stories use stories.getVideoUploadServer, multipart video_file, stories.save and stories.getById. Story IDs and nested video IDs are distinct. Do not report verified success without matching the exact saved native media identity. Story duration/size acceptance is provider-specific; the current official schema does not state numeric limits and the documentation endpoint was unavailable. The owner's 33.513-second clip must not be silently shortened.

## Verification required
Regression checks cover images, MP4 ingress replay/concurrency/quota, Telegram native video attributes, VK token role/identity/processing errors, uncertain upload without repeat, and exact video Story readback. Real publication happens only through the separately approved content workflow.

Primary references: https://github.com/VKCOM/vk-php-sdk#53-uploading-video-files ; https://github.com/VKCOM/vk-java-sdk/blob/master/sdk/src/main/java/com/vk/api/sdk/actions/Upload.java ; https://github.com/VKCOM/vk-api-schema/tree/master/video ; https://github.com/VKCOM/vk-api-schema/tree/master/stories
