// Mic -> 24 kHz mono PCM16 in 100 ms frames, plus each frame's loudness (RMS) for pause detection.
// Resamples itself: Safari ignores a requested AudioContext sample rate on some devices.
const TARGET_RATE = 24000
const FRAME = TARGET_RATE / 10

class PcmWorklet extends AudioWorkletProcessor {
  constructor() {
    super()
    this.step = sampleRate / TARGET_RATE
    this.pos = 0
    this.frame = new Int16Array(FRAME)
    this.filled = 0
    this.sumSquares = 0
  }

  process(inputs) {
    const input = inputs[0] && inputs[0][0]
    if (!input) return true
    while (this.pos < input.length) {
      const i = Math.floor(this.pos)
      const a = input[i]
      const b = i + 1 < input.length ? input[i + 1] : a
      const s = Math.max(-1, Math.min(1, a + (b - a) * (this.pos - i)))
      this.frame[this.filled++] = s < 0 ? s * 0x8000 : s * 0x7fff
      this.sumSquares += s * s
      if (this.filled === FRAME) {
        const rms = Math.sqrt(this.sumSquares / FRAME)
        this.port.postMessage({ pcm: this.frame.buffer, rms }, [this.frame.buffer])
        this.frame = new Int16Array(FRAME)
        this.filled = 0
        this.sumSquares = 0
      }
      this.pos += this.step
    }
    this.pos -= input.length
    return true
  }
}

registerProcessor('pcm-worklet', PcmWorklet)
