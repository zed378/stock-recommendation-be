/**
 * The notification sound, synthesised in the browser.
 *
 * No audio file and no network request. A tone is a few lines of Web Audio, so
 * shipping a WAV would add an asset to the bundle, a request to the page, and a
 * decode - to produce a sound that can be described in arithmetic. It also
 * means nothing here depends on a CDN or on the strict CSP letting a media URL
 * through: there is no URL.
 *
 * Two notes rather than one. A single beep is the vocabulary of an error; a
 * rising pair reads as "something arrived", which is what actually happened.
 */

const MUTE_KEY = "aidss.notifications.muted";

/** A5 then D6 - a rising fourth, short enough not to be an event in itself. */
const NOTES = [
  { frequency: 880, start: 0, duration: 0.12 },
  { frequency: 1174.66, start: 0.1, duration: 0.22 },
];

//: Deliberately quiet. This plays without being asked for, so it should be
//: audible in a quiet room and ignorable in a loud one - not the other way
//: round.
const PEAK_GAIN = 0.07;

let context: AudioContext | null = null;

/**
 * The shared AudioContext, created on first use.
 *
 * Lazily, because a context created at import time starts suspended under every
 * browser's autoplay policy and some log a warning for it. There is no reason
 * to hold audio hardware open on a page that may never make a sound.
 */
function audioContext(): AudioContext | null {
  if (context) return context;
  const Ctor =
    window.AudioContext ??
    (window as unknown as { webkitAudioContext?: typeof AudioContext })
      .webkitAudioContext;
  if (!Ctor) return null;
  try {
    context = new Ctor();
    return context;
  } catch {
    // A browser that refuses to give us one is a browser that stays silent.
    // Never a reason to break the notification itself.
    return null;
  }
}

export function isMuted(): boolean {
  try {
    return localStorage.getItem(MUTE_KEY) === "1";
  } catch {
    return false;
  }
}

export function setMuted(muted: boolean): void {
  try {
    localStorage.setItem(MUTE_KEY, muted ? "1" : "0");
  } catch {
    // Private browsing with storage denied. The preference lasts the session
    // rather than being lost, which is better than throwing at a click.
  }
}

/**
 * Wake the audio context after a user gesture.
 *
 * Every browser starts it suspended until the page has been interacted with,
 * and a reload resets that. Called from a click handler, this is what makes the
 * first chime after a page load actually audible instead of silently dropped.
 */
export function unlockAudio(): void {
  if (isMuted()) return;
  const ctx = audioContext();
  if (ctx?.state === "suspended") void ctx.resume();
}

/** Play the chime. Never throws, and does nothing when muted. */
export function playChime(): void {
  if (isMuted()) return;

  const ctx = audioContext();
  if (!ctx) return;

  // Still suspended means no gesture has reached this page yet. Resuming is
  // asynchronous and would land after the notes were scheduled, so this pass is
  // simply silent rather than played late and out of order.
  if (ctx.state === "suspended") {
    void ctx.resume();
    return;
  }

  const now = ctx.currentTime;
  for (const note of NOTES) {
    const oscillator = ctx.createOscillator();
    const gain = ctx.createGain();

    oscillator.type = "sine";
    oscillator.frequency.value = note.frequency;

    // Ramped, not switched. A gain that jumps from 0 to full is a step
    // discontinuity in the waveform, and that is heard as a click on top of
    // the note - which is exactly the harsh edge this sound should not have.
    const start = now + note.start;
    const end = start + note.duration;
    gain.gain.setValueAtTime(0.0001, start);
    gain.gain.exponentialRampToValueAtTime(PEAK_GAIN, start + 0.015);
    gain.gain.exponentialRampToValueAtTime(0.0001, end);

    oscillator.connect(gain).connect(ctx.destination);
    oscillator.start(start);
    oscillator.stop(end);
    // Released once it has finished, so a long session does not accumulate
    // one dead node per notification.
    oscillator.onended = () => {
      oscillator.disconnect();
      gain.disconnect();
    };
  }
}
