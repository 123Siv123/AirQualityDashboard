(function () {
    let settings = {};
    let profilePresets = {};

    function $(id) {
        return document.getElementById(id);
    }

    function showToast(message, isError) {
        const toast = $("settingsToast");
        if (!toast) return;
        toast.textContent = message;
        toast.hidden = false;
        toast.classList.toggle("settings-toast--error", !!isError);
        toast.classList.add("settings-toast--show");
        setTimeout(function () {
            toast.classList.remove("settings-toast--show");
        }, 3200);
    }

    function fillForm(data) {
        settings = data;
        profilePresets = data.profile_presets || {};

        $("gas_sensor_profile").value = data.gas_sensor_profile || "standard";
        $("gas_safe_max").value = data.gas_safe_max;
        $("gas_moderate").value = data.gas_moderate;
        $("gas_moderate_max").value = data.gas_moderate_max;
        $("gas_critical").value = data.gas_critical;
        $("smoke_latch_sec").value = data.smoke_latch_sec;
        $("serial_port").value = data.serial_port || "COM7";
        $("serial_baud").value = data.serial_baud || 115200;
        $("twilio_enabled").checked = !!data.twilio_enabled;
        $("twilio_sms_moderate").checked = !!data.twilio_sms_moderate;
        $("twilio_from_number").value = data.twilio_from_number || "";
        $("twilio_to_number").value = data.twilio_to_number || "";
        $("twilio_sms_cooldown_sec").value = data.twilio_sms_cooldown_sec || 300;
        $("twilio_account_sid_masked").value = data.twilio_account_sid_masked || "—";

        updateSmsUi(data.twilio_status || {});
    }

    function updateSmsUi(status) {
        const pill = $("smsStatusPill");
        if (pill) {
            if (status.enabled) {
                pill.textContent = "ON";
                pill.className = "settings-status-pill settings-status-pill--on";
            } else if (status.configured) {
                pill.textContent = "Ready";
                pill.className = "settings-status-pill settings-status-pill--off";
            } else {
                pill.textContent = "Not configured";
                pill.className = "settings-status-pill settings-status-pill--off";
            }
        }
        $("smsLastSent").textContent = status.last_sent_iso
            ? new Date(status.last_sent_iso).toLocaleString()
            : "Never";
        $("smsSendCount").textContent = status.send_count != null ? status.send_count : "0";
    }

    function collectPayload(applyPreset) {
        return {
            gas_sensor_profile: $("gas_sensor_profile").value,
            gas_safe_max: parseInt($("gas_safe_max").value, 10),
            gas_moderate: parseInt($("gas_moderate").value, 10),
            gas_moderate_max: parseInt($("gas_moderate_max").value, 10),
            gas_critical: parseInt($("gas_critical").value, 10),
            gas_poor_max: parseInt($("gas_critical").value, 10) + 60,
            gas_moderate_clear: Math.max(0, parseInt($("gas_moderate").value, 10) - 6),
            gas_critical_clear: Math.max(0, parseInt($("gas_critical").value, 10) - 6),
            smoke_latch_sec: parseInt($("smoke_latch_sec").value, 10),
            serial_port: $("serial_port").value.trim(),
            serial_baud: parseInt($("serial_baud").value, 10),
            twilio_enabled: $("twilio_enabled").checked,
            twilio_sms_moderate: $("twilio_sms_moderate").checked,
            twilio_from_number: $("twilio_from_number").value.trim(),
            twilio_to_number: $("twilio_to_number").value.trim(),
            twilio_sms_cooldown_sec: parseInt($("twilio_sms_cooldown_sec").value, 10),
            apply_profile_preset: !!applyPreset,
        };
    }

    function applyPresetToForm() {
        const profile = $("gas_sensor_profile").value;
        const preset = profilePresets[profile];
        if (!preset) return;
        $("gas_safe_max").value = preset.gas_safe_max;
        $("gas_moderate").value = preset.gas_moderate;
        $("gas_moderate_max").value = preset.gas_moderate_max;
        $("gas_critical").value = preset.gas_critical;
        showToast("Loaded " + profile.toUpperCase() + " preset — click Save to apply");
    }

    async function saveSettings(applyPreset) {
        try {
            const res = await fetch("/api/settings", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify(collectPayload(applyPreset)),
            });
            const data = await res.json();
            if (!res.ok || !data.ok) {
                const msg = (data.errors && data.errors.join(" ")) || data.error || "Save failed";
                showToast(msg, true);
                return;
            }
            fillForm(data.settings);
            $("serialStatusText").textContent = data.serial_connected
                ? "Connected on " + data.settings.serial_port
                : "Offline / demo mode (" + data.settings.serial_port + ")";
            showToast(data.message || "Settings saved");
        } catch (err) {
            showToast("Network error saving settings", true);
        }
    }

    document.addEventListener("DOMContentLoaded", function () {
        try {
            fillForm(JSON.parse($("initialSettings").textContent));
        } catch (e) {
            console.warn("Settings parse failed", e);
        }

        $("serialStatusText").textContent = "Check dashboard or reconnect";

        $("settingsForm").addEventListener("submit", function (e) {
            e.preventDefault();
            saveSettings(false);
        });

        const saveBack = $("saveAndBackBtn");
        if (saveBack) {
            saveBack.addEventListener("click", async function () {
                await saveSettings(false);
                window.location.href = "/dashboard";
            });
        }

        $("loadPresetBtn").addEventListener("click", applyPresetToForm);

        $("reconnectSerialBtn").addEventListener("click", async function () {
            try {
                const res = await fetch("/api/settings/reconnect-serial", { method: "POST" });
                const data = await res.json();
                $("serialStatusText").textContent = data.serial_connected
                    ? "Connected on " + data.serial_port
                    : "Unavailable — demo mode";
                showToast(data.serial_connected ? "Serial connected" : "Serial not available");
            } catch (err) {
                showToast("Reconnect failed", true);
            }
        });

        $("testSmsBtn").addEventListener("click", async function () {
            try {
                const res = await fetch("/api/sms/test", { method: "POST" });
                const data = await res.json();
                if (data.ok) {
                    updateSmsUi(data.status || {});
                    showToast("Test SMS sent");
                } else {
                    showToast(data.error || "Test SMS failed", true);
                }
            } catch (err) {
                showToast("Test SMS request failed", true);
            }
        });
    });
})();
