import enum


class FileProcessingStatus(str, enum.Enum):
    queued = "queued"
    processing = "processing"
    ready = "ready"
    failed = "failed"


class LectureStatus(str, enum.Enum):
    """Original lecture: uploaded -> transcribing -> transcribed -> translating -> indexing -> ready.
    English lecture (optional, on top of ready): chunking -> scripting -> voicing -> assembling
    -> english_ready. `failed` can follow any of them."""

    uploaded = "uploaded"
    transcribing = "transcribing"
    transcribed = "transcribed"
    translating = "translating"
    indexing = "indexing"
    ready = "ready"
    chunking = "chunking"
    scripting = "scripting"
    voicing = "voicing"
    assembling = "assembling"
    english_ready = "english_ready"
    failed = "failed"


IDLE_STATUSES = {LectureStatus.ready, LectureStatus.english_ready, LectureStatus.failed}
