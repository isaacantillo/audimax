import enum


class LectureStatus(str, enum.Enum):
    """Original lecture: uploaded -> transcribing -> transcribed -> translating -> summarizing -> ready.
    English version (optional, on top of ready): chunking -> scripting -> english_ready. `failed` can follow any of them."""

    uploaded = "uploaded"
    transcribing = "transcribing"
    transcribed = "transcribed"
    translating = "translating"
    summarizing = "summarizing"
    ready = "ready"
    chunking = "chunking"
    scripting = "scripting"
    english_ready = "english_ready"
    failed = "failed"


IDLE_STATUSES = {LectureStatus.ready, LectureStatus.english_ready, LectureStatus.failed}
