(function () {
    const VOICE_ALERT_TEXT = "Warning. Smoke detected.";
    const GAS_CRITICAL_DEFAULT = 281;
    const ALERT_COOLDOWN_MS = 45000;

    let audioUnlocked = localStorage.getItem("audioUnlocked") === "1";
    let sharedAudioContext = null;
    let unlockBar = null;
    let enableBtn = null;
    let voiceBadge = null;

    let wasSmokeActive = false;
    let canTriggerAgain = true;
    let lastAlertPlayedAt = 0;

    function parseGas(gasText) {
        return parseFloat(String(gasText || "").replace(/[^\d.]/g, "")) || 0;
    }

    /**
     * Voice/beep only when smoke is detected (gas >= critical threshold).
     * Does NOT alert for moderate air quality, temperature, or humidity alone.
     */
    function isSmokeDetected(payload) {
        if (!payload) {
            return false;
        }

        if (payload.smoke_detected === true) {
            return true;
        }

        if (payload.smoke_recent === true) {
            return true;
        }

        const gasCritical =
            typeof window.AQ_GAS_CRITICAL === "number"
                ? window.AQ_GAS_CRITICAL
                : GAS_CRITICAL_DEFAULT;

        const gasValue = parseGas(payload.sensor && payload.sensor.gas);
        if (gasValue >= gasCritical) {
            return true;
        }

        const status = ((payload.sensor && payload.sensor.status) || "").toLowerCase();
        if (status.includes("smoke") && status.includes("detect")) {
            return true;
        }

        return false;
    }

    function updateSoundUnlockUI(smokeActive) {
        if (!unlockBar) {
            return;
        }
        unlockBar.hidden = false;
        unlockBar.classList.toggle("sound-unlock-bar--urgent", smokeActive && !audioUnlocked);

        const textEl = document.getElementById("soundUnlockText");
        if (textEl) {
            if (audioUnlocked) {
                textEl.textContent = smokeActive
                    ? "Smoke detected — playing beep + warning voice"
                    : "Smoke alerts are enabled (will beep/voice on detection)";
            } else {
                textEl.textContent = smokeActive
                    ? "Smoke detected — click to enable beep + warning voice"
                    : "Enable beep + warning voice for smoke (click once)";
            }
        }
        if (enableBtn) {
            enableBtn.textContent = audioUnlocked
                ? "✓ Smoke alerts on"
                : "Enable smoke alerts";
        }
    }

    function setVoiceBadgeActive(active) {
        if (!voiceBadge) {
            return;
        }
        voiceBadge.classList.toggle("is-active", active);
        voiceBadge.classList.toggle("voice-speaking", active);
    }

    async function unlockAudio() {
        audioUnlocked = true;
        localStorage.setItem("audioUnlocked", "1");
        updateSoundUnlockUI(true);

        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        if (!AudioCtx) {
            return;
        }

        if (!sharedAudioContext) {
            sharedAudioContext = new AudioCtx();
        }
        if (sharedAudioContext.state === "suspended") {
            await sharedAudioContext.resume();
        }
    }

    async function playShortBeep() {
        if (!audioUnlocked) {
            return;
        }

        const AudioCtx = window.AudioContext || window.webkitAudioContext;
        if (!AudioCtx) {
            return;
        }

        if (!sharedAudioContext) {
            sharedAudioContext = new AudioCtx();
        }
        if (sharedAudioContext.state === "suspended") {
            await sharedAudioContext.resume();
        }

        const start = sharedAudioContext.currentTime;
        const oscillator = sharedAudioContext.createOscillator();
        const gain = sharedAudioContext.createGain();
        oscillator.type = "sine";
        oscillator.frequency.value = 880;
        gain.gain.setValueAtTime(0.28, start);
        gain.gain.exponentialRampToValueAtTime(0.01, start + 0.2);
        oscillator.connect(gain);
        gain.connect(sharedAudioContext.destination);
        oscillator.start(start);
        oscillator.stop(start + 0.22);
    }

    function speakSmokeAlert() {
        if (!window.speechSynthesis) {
            return;
        }

        window.speechSynthesis.cancel();
        const utterance = new SpeechSynthesisUtterance(VOICE_ALERT_TEXT);
        utterance.lang = "en-US";
        utterance.rate = 0.92;
        utterance.pitch = 1;
        utterance.volume = 1;

        const voices = window.speechSynthesis.getVoices();
        const englishVoice = voices.find(function (voice) {
            return voice.lang && voice.lang.toLowerCase().startsWith("en");
        });
        if (englishVoice) {
            utterance.voice = englishVoice;
        }

        utterance.onstart = function () {
            setVoiceBadgeActive(true);
        };
        utterance.onend = function () {
            if (voiceBadge) {
                voiceBadge.classList.remove("voice-speaking");
            }
        };

        window.speechSynthesis.speak(utterance);
    }

    async function fireSmokeAlertOnce() {
        const now = Date.now();
        if (now - lastAlertPlayedAt < ALERT_COOLDOWN_MS) {
            return;
        }
        lastAlertPlayedAt = now;
        canTriggerAgain = false;

        await playShortBeep();
        speakSmokeAlert();
    }

    async function maybePlayAlert(payload) {
        if (!payload) {
            return;
        }

        const smokeActive = isSmokeDetected(payload);

        updateSoundUnlockUI(smokeActive);

        if (!smokeActive) {
            wasSmokeActive = false;
            canTriggerAgain = true;
            setVoiceBadgeActive(false);
            if (window.speechSynthesis) {
                window.speechSynthesis.cancel();
            }
            return;
        }

        if (!audioUnlocked) {
            return;
        }

        const enteredSmoke = !wasSmokeActive;
        wasSmokeActive = true;

        if (enteredSmoke && canTriggerAgain) {
            await fireSmokeAlertOnce();
        }
    }

    async function fetchAndCheck() {
        try {
            const response = await fetch("/api/alerts");
            if (!response.ok) {
                return null;
            }
            const payload = await response.json();
            await maybePlayAlert(payload);
            return payload;
        } catch (error) {
            console.warn("Alert check failed", error);
            return null;
        }
    }

    function init(options) {
        options = options || {};
        unlockBar = document.getElementById(options.unlockBarId || "soundUnlockBar");
        enableBtn = document.getElementById(options.enableBtnId || "enableSoundBtn");
        voiceBadge = document.getElementById(options.voiceBadgeId || "voiceAlertBadge");

        if (window.speechSynthesis) {
            window.speechSynthesis.getVoices();
            window.speechSynthesis.onvoiceschanged = function () {
                window.speechSynthesis.getVoices();
            };
        }

        if (enableBtn) {
            enableBtn.addEventListener("click", async function () {
                await unlockAudio();
            });
        }

        updateSoundUnlockUI(false);

        if (options.poll) {
            const interval = options.pollMs || 2000;
            fetchAndCheck();
            setInterval(fetchAndCheck, interval);
        }
    }

    window.AirQualityAlerts = {
        init: init,
        maybePlayAlert: maybePlayAlert,
        unlockAudio: unlockAudio,
        fetchAndCheck: fetchAndCheck,
        isSmokeDetected: isSmokeDetected,
        isPoorAirQuality: isSmokeDetected,
        isCriticalHazard: isSmokeDetected,
    };
})();
