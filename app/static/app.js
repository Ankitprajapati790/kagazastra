// KagazAstra Client Engine
document.addEventListener("DOMContentLoaded", () => {
    // Current date fill
    const today = new Date();
    const dStr = `${String(today.getDate()).padStart(2, '0')}/${String(today.getMonth() + 1).padStart(2, '0')}/${today.getFullYear()}`;
    const dateEl = document.getElementById("currentDateStr");
    if (dateEl) dateEl.innerText = dStr;
    const dopInput = document.getElementById("dop");
    if (dopInput) dopInput.value = dStr;

    // Signature Canvas setup
    const canvas = document.getElementById("sigCanvas");
    const ctx = canvas ? canvas.getContext("2d") : null;
    let isDrawing = false;

    if (canvas && ctx) {
        ctx.strokeStyle = "#1e293b";
        ctx.lineWidth = 2.5;
        ctx.lineCap = "round";

        function getPos(e) {
            const rect = canvas.getBoundingClientRect();
            return {
                x: (e.clientX || (e.touches && e.touches[0].clientX)) - rect.left,
                y: (e.clientY || (e.touches && e.touches[0].clientY)) - rect.top
            };
        }

        function startDrawing(e) {
            isDrawing = true;
            const p = getPos(e);
            ctx.beginPath();
            ctx.moveTo(p.x, p.y);
            e.preventDefault();
        }

        function draw(e) {
            if (!isDrawing) return;
            const p = getPos(e);
            ctx.lineTo(p.x, p.y);
            ctx.stroke();
            e.preventDefault();
        }

        function stopDrawing() {
            isDrawing = false;
        }

        canvas.addEventListener("mousedown", startDrawing);
        canvas.addEventListener("mousemove", draw);
        window.addEventListener("mouseup", stopDrawing);

        canvas.addEventListener("touchstart", startDrawing);
        canvas.addEventListener("touchmove", draw);
        window.addEventListener("touchend", stopDrawing);

        document.getElementById("clearSig").addEventListener("click", () => {
            ctx.clearRect(0, 0, canvas.width, canvas.height);
        });

        document.getElementById("downloadSig").addEventListener("click", () => {
            const link = document.createElement("a");
            link.download = "kagazastra_signature.png";
            link.href = canvas.toDataURL("image/png");
            link.click();
        });

        document.getElementById("addDateStamp").addEventListener("click", () => {
            ctx.font = "bold 16px sans-serif";
            ctx.fillStyle = "#0f172a";
            ctx.fillText(`Dated: ${dStr}`, 20, canvas.height - 25);
        });
    }

    // Photo Resizer Form
    const resizerForm = document.getElementById("resizerForm");
    if (resizerForm) {
        resizerForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const fileInput = document.getElementById("photoInput");
            if (!fileInput.files[0]) {
                alert("Kripya ek photo select karein!");
                return;
            }

            const formData = new FormData();
            formData.append("file", fileInput.files[0]);
            formData.append("preset", document.getElementById("examPreset").value);
            formData.append("target_kb", document.getElementById("targetKb").value);
            formData.append("candidate_name", document.getElementById("candidateName").value);
            formData.append("dop", document.getElementById("dop").value);

            try {
                const res = await fetch("/api/resize-photo", {
                    method: "POST",
                    body: formData
                });
                if (!res.ok) throw new Error("Resize failed");

                const blob = await res.blob();
                const url = URL.createObjectURL(blob);

                const previewImg = document.getElementById("resizerPreview");
                const previewText = document.getElementById("previewText");
                previewImg.src = url;
                previewImg.classList.remove("hidden");
                previewText.innerText = `Final Size: ~${(blob.size / 1024).toFixed(1)} KB (Ready for Sarkari Portal)`;

                // Auto download
                const a = document.createElement("a");
                a.href = url;
                a.download = `sarkari_processed_${fileInput.files[0].name}`;
                a.click();
            } catch (err) {
                alert("Error processing photo: " + err.message);
            }
        });
    }

    // Roll Number Search Form
    const rollSearchForm = document.getElementById("rollSearchForm");
    if (rollSearchForm) {
        rollSearchForm.addEventListener("submit", async (e) => {
            e.preventDefault();
            const fileInput = document.getElementById("searchPdfFile");
            const query = document.getElementById("searchQuery").value;
            const resultBox = document.getElementById("searchResult");

            resultBox.classList.remove("hidden");
            resultBox.className = "p-3 rounded-lg text-sm font-medium bg-slate-100 text-slate-700";
            resultBox.innerText = "Gazette document scan ho raha hai...";

            const formData = new FormData();
            formData.append("file", fileInput.files[0]);
            formData.append("query", query);

            try {
                const res = await fetch("/api/search/roll-number", {
                    method: "POST",
                    body: formData
                });
                const data = await res.json();

                if (data.found) {
                    resultBox.className = "p-3 rounded-lg text-sm font-medium bg-emerald-100 text-emerald-800";
                    resultBox.innerText = `✓ Mil gaya! Roll number / Query "${data.query}" document ke Page(s): ${data.matched_pages.join(", ")} par mila hai.`;
                } else {
                    resultBox.className = "p-3 rounded-lg text-sm font-medium bg-rose-100 text-rose-800";
                    resultBox.innerText = `❌ Roll number "${data.query}" is document me nahi mila.`;
                }
            } catch (err) {
                resultBox.className = "p-3 rounded-lg text-sm font-medium bg-rose-100 text-rose-800";
                resultBox.innerText = "Scan fail hua: " + err.message;
            }
        });
    }

    // Floating AstraBot: image instructions, voice input, and processed-image download.
    const sendActionBtn = document.getElementById("sendActionBtn");
    const voiceInput = document.getElementById("voiceCommandInput");
    const chatContainer = document.getElementById("astrabotChatContainer");
    const aFileInput = document.getElementById("astrabotFileInput");
    const cNameDirect = document.getElementById("candidateNameDirect");
    const panel = document.getElementById("astrabotPanel");
    const launcher = document.getElementById("astrabotLauncher");
    const closeButton = document.getElementById("closeAstrabot");
    const openButton = document.getElementById("openAstrabot");
    let reopenTimer;

    function openAstrabot() {
        window.clearTimeout(reopenTimer);
        panel.classList.remove("hidden");
        launcher.classList.add("hidden");
        voiceInput.focus();
    }

    function closeAstrabot() {
        panel.classList.add("hidden");
        launcher.classList.add("hidden");
        window.clearTimeout(reopenTimer);
        reopenTimer = window.setTimeout(() => {
            launcher.classList.remove("hidden");
        }, 30000);
    }

    launcher.addEventListener("click", openAstrabot);
    openButton.addEventListener("click", openAstrabot);
    closeButton.addEventListener("click", closeAstrabot);

    function addChatMessage(textContent, isUser = false, download = null) {
        const row = document.createElement("div");
        row.className = `flex items-start gap-2 ${isUser ? "justify-end" : ""}`;
        const avatar = document.createElement(isUser ? "div" : "img");
        avatar.className = "h-7 w-7 shrink-0 rounded-full object-cover";
        if (isUser) {
            avatar.classList.add("flex", "items-center", "justify-center", "bg-slate-700", "text-xs", "text-white");
            avatar.textContent = "You";
        } else {
            avatar.src = "/static/astrabot-assistant.jpg";
            avatar.alt = "AstraBot";
        }

        const bubble = document.createElement("div");
        bubble.className = `max-w-[85%] rounded-lg p-2.5 text-xs shadow-sm ${isUser ? "bg-rose-600 text-white" : "border bg-white text-slate-800"}`;
        const message = document.createElement("p");
        message.textContent = textContent;
        bubble.appendChild(message);

        if (download) {
            const link = document.createElement("a");
            link.href = download.url;
            link.download = download.filename;
            link.className = "mt-2.5 inline-block border-t pt-2 font-bold text-emerald-600";
            link.textContent = "✓ Ready to Download";
            bubble.appendChild(link);
        }

        if (isUser) {
            row.append(bubble, avatar);
        } else {
            row.append(avatar, bubble);
        }
        chatContainer.appendChild(row);
        chatContainer.scrollTop = chatContainer.scrollHeight;
    }

    async function executeAstrabot() {
        const command = voiceInput.value.trim();
        if (!command) {
            addChatMessage("Please type or say an image instruction first.");
            return;
        }
        if (!aFileInput.files[0]) {
            addChatMessage("Please select a photo first, then send your instruction.");
            return;
        }

        const formData = new FormData();
        formData.append("command", command);
        formData.append("file", aFileInput.files[0]);
        if (cNameDirect.value.trim()) {
            formData.append("candidate_name", cNameDirect.value.trim());
        }

        addChatMessage(command, true);
        voiceInput.value = "";
        sendActionBtn.disabled = true;
        sendActionBtn.textContent = "Working...";
        try {
            const response = await fetch("/api/astrabot/execute", {
                method: "POST",
                body: formData
            });
            const data = await response.json();
            if (!response.ok) {
                throw new Error(data.detail || "Ollama image processing failed.");
            }

            const download = data.download_file
                ? { url: data.download_file, filename: data.filename }
                : null;
            addChatMessage(data.bot_reply, false, download);
        } catch (error) {
            addChatMessage(`Execution Error: ${error.message}`);
        } finally {
            sendActionBtn.disabled = false;
            sendActionBtn.textContent = "Send";
        }
    }

    sendActionBtn.addEventListener("click", executeAstrabot);
    voiceInput.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
            event.preventDefault();
            executeAstrabot();
        }
    });

    const micBtn = document.getElementById("micBtn");
    if ("webkitSpeechRecognition" in window || "SpeechRecognition" in window) {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        const recognition = new SpeechRecognition();
        recognition.lang = "en-US";
        recognition.continuous = false;
        recognition.interimResults = false;

        micBtn.addEventListener("click", () => {
            try {
                recognition.start();
                micBtn.innerHTML = '<i class="fa-solid fa-circle-notch fa-spin"></i>';
                micBtn.setAttribute("aria-label", "Listening");
            } catch (error) {
                addChatMessage(`Microphone error: ${error.message}`);
            }
        });

        recognition.onresult = (event) => {
            voiceInput.value = event.results[0][0].transcript;
            executeAstrabot();
        };
        recognition.onerror = (event) => {
            addChatMessage(`Microphone error: ${event.error}`);
        };
        recognition.onend = () => {
            micBtn.innerHTML = '<i class="fa-solid fa-microphone"></i>';
            micBtn.setAttribute("aria-label", "Use microphone");
        };
    } else {
        micBtn.disabled = true;
        micBtn.title = "Voice input is not supported by this browser.";
    }
});

// UPI Payment Handler
async function payPlan(planId) {
    try {
        const sessionResponse = await fetch("/api/auth/me");
        if (!sessionResponse.ok) {
            window.location.href = "/login";
            return;
        }
        const session = await sessionResponse.json();
        const res = await fetch("/api/billing/create-upi-order", {
            method: "POST",
            headers: {
                "Content-Type": "application/json",
                "X-CSRF-Token": session.csrf_token
            },
            body: JSON.stringify({
                plan_id: planId
            }),
            credentials: "same-origin"
        });
        const data = await res.json();
        if (!res.ok) throw new Error(data.detail || "Plan request failed.");
        alert(`${data.message}\nRequest: ${data.transaction_id}\nAmount: ₹${data.amount}`);
        window.location.href = "/client";
    } catch (err) {
        alert("Plan request failed: " + err.message);
    }
}
