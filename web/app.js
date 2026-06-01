document.addEventListener("DOMContentLoaded", () => {
    // Elements
    const canvas = document.getElementById("screenshot-canvas");
    const ctx = canvas.getContext("2d");
    const container = document.getElementById("canvas-container");
    const noCaptureOverlay = document.getElementById("no-capture-overlay");
    const consoleOutput = document.getElementById("console-output");
    
    // Status Pills
    const statusOllama = document.getElementById("status-ollama");
    const statusTesseract = document.getElementById("status-tesseract");
    const statusLoop = document.getElementById("status-loop");

    // Action Buttons
    const btnRunOnce = document.getElementById("btn-run-once");
    const btnStartLoop = document.getElementById("btn-start-loop");
    const btnStopLoop = document.getElementById("btn-stop-loop");
    const btnClearRegion = document.getElementById("btn-clear-region");
    const btnCapture = document.getElementById("btn-capture");
    const btnClearConsole = document.getElementById("btn-clear-console");
    const btnRefreshModels = document.getElementById("btn-refresh-models");
    const btnSaveConfig = document.getElementById("btn-save-config");
    
    // Config Form Inputs
    const formOllamaHost = document.getElementById("ollama_host");
    const formModel = document.getElementById("model");
    const formLang = document.getElementById("lang");
    const formPsm = document.getElementById("psm");
    const formTesseractCmd = document.getElementById("tesseract_cmd");
    const formClick = document.getElementById("click");
    const formConfirm = document.getElementById("confirm");
    const formSafeMode = document.getElementById("safe_mode");
    const formMinClickScore = document.getElementById("min_click_score");
    const formInterval = document.getElementById("interval");
    const formAutoScroll = document.getElementById("auto_scroll");
    const formScrollAmount = document.getElementById("scroll_amount");
    const formScrollDelay = document.getElementById("scroll_delay");
    const btnToggleViewer = document.getElementById("btn-toggle-viewer");
    
    // Config Slider Values
    const valMinClickScore = document.getElementById("val-min-click-score");
    const valInterval = document.getElementById("val-interval");
    const regionBadge = document.getElementById("region-badge");

    // Results Box Elements
    const resultQuestion = document.getElementById("result-question");
    const resultOptions = document.getElementById("result-options");
    const resultAnswer = document.getElementById("result-answer");
    const resultConfidence = document.getElementById("result-confidence");
    const resultReason = document.getElementById("result-reason");
    const planText = document.getElementById("plan-text");
    const planCoords = document.getElementById("plan-coords");
    const planScore = document.getElementById("plan-score");
    const planMode = document.getElementById("plan-mode");
    const aiAnswerBox = document.getElementById("ai-answer-box");

    // Confirmation Modal Elements
    const confirmModal = document.getElementById("confirm-modal");
    const btnModalCancel = document.getElementById("btn-modal-cancel");
    const btnModalApprove = document.getElementById("btn-modal-approve");
    const modalPlanText = document.getElementById("modal-plan-text");
    const modalPlanCoords = document.getElementById("modal-plan-coords");
    const modalPlanScore = document.getElementById("modal-plan-score");

    // Command Bar Elements
    const cmdBar = document.getElementById("command-bar-dialog");
    const cmdInput = document.getElementById("cmd-input");
    const cmdResults = document.getElementById("cmd-results");
    const btnCmdTrigger = document.getElementById("btn-cmdk-trigger");
    const btnCloseCmdBar = document.getElementById("btn-close-cmd-bar");

    // Application State
    let isLoopRunning = false;
    let currentRegion = null; // [x, y, w, h]
    let currentConfig = {};
    let latestScreenshotUrl = null;
    let screenshotImg = new Image();
    let ws = null;

    // Canvas drawing state
    let isDrawing = false;
    let startX = 0, startY = 0;
    let curX = 0, curY = 0;

    // Command palette list
    const commandsList = [
        { name: "/solve", desc: "Ejecuta el ciclo solver una vez", icon: "⚡", shortcut: "Ctrl+Enter" },
        { name: "/loop start", desc: "Iniciar bucle de resolución continua", icon: "🔄", shortcut: "" },
        { name: "/loop stop", desc: "Detener bucle continuo", icon: "⏹️", shortcut: "" },
        { name: "/click on", desc: "Habilitar clics automáticos", icon: "🖱️", shortcut: "" },
        { name: "/click off", desc: "Desactivar clics automáticos", icon: "🚫", shortcut: "" },
        { name: "/confirm on", desc: "Activar confirmación previa a clics", icon: "❓", shortcut: "" },
        { name: "/confirm off", desc: "Desactivar confirmación previa a clics", icon: "🚀", shortcut: "" },
        { name: "/screenshot", desc: "Capturar pantalla fresca", icon: "📸", shortcut: "" },
        { name: "/region clear", desc: "Restablecer región a pantalla completa", icon: "🖥️", shortcut: "" },
        { name: "/scroll down", desc: "Simular scroll hacia abajo", icon: "⬇️", shortcut: "" },
        { name: "/scroll up", desc: "Simular scroll hacia arriba", icon: "⬆️", shortcut: "" },
        { name: "/scroll auto on", desc: "Activar scroll tras responder", icon: "🔄", shortcut: "" },
        { name: "/scroll auto off", desc: "Desactivar scroll tras responder", icon: "⏹️", shortcut: "" },
        { name: "/status", desc: "Consultar estado de Ollama e IA", icon: "📡", shortcut: "" },
        { name: "/help", desc: "Mostrar comandos de ayuda", icon: "💡", shortcut: "" }
    ];
    let selectedCmdIndex = 0;
    let filteredCommands = [];

    // --- LOGS ---
    function log(message, level = "info") {
        const timestamp = new Date().toLocaleTimeString();
        const line = document.createElement("div");
        line.className = `log-line ${level.toLowerCase()}`;
        line.textContent = `[${timestamp}] ${message}`;
        consoleOutput.appendChild(line);
        consoleOutput.scrollTop = consoleOutput.scrollHeight;
    }

    // --- WEBSOCKET CONNECTION ---
    function initWebSocket() {
        const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        const wsUrl = `${protocol}//${window.location.host}/ws`;
        
        log("Conectando al WebSocket del backend...", "system");
        ws = new WebSocket(wsUrl);

        ws.onopen = () => {
            log("WebSocket conectado correctamente.", "success");
        };

        ws.onmessage = (event) => {
            const data = JSON.parse(event.data);
            handleWsMessage(data);
        };

        ws.onclose = () => {
            log("Conexión WebSocket cerrada. Reintentando en 3s...", "warning");
            setTimeout(initWebSocket, 3000);
        };

        ws.onerror = (err) => {
            console.error("WS Error:", err);
        };
    }

    function handleWsMessage(data) {
        switch (data.type) {
            case "init":
                currentConfig = data.config;
                isLoopRunning = data.loop_running;
                syncConfigToForm(data.config);
                updateLoopPill(data.loop_running);
                checkSystemStatus();
                
                if (data.last_run && Object.keys(data.last_run).length > 0) {
                    displayRunResults(data.last_run);
                }
                
                // Fetch first screenshot
                loadLatestScreenshot();
                
                if (data.pending_confirm) {
                    // Fetch status to load pending plan details
                    checkSystemStatus();
                }
                break;

            case "log":
                log(data.message, data.level);
                break;

            case "screenshot":
                log("Cargando nueva captura de pantalla...", "system");
                latestScreenshotUrl = data.path;
                loadLatestScreenshot();
                break;

            case "status":
                isLoopRunning = data.loop_running;
                updateLoopPill(data.loop_running);
                break;

            case "config":
                currentConfig = data.config;
                syncConfigToForm(data.config);
                break;

            case "result":
                displayRunResults(data.data);
                break;

            case "pending_confirm":
                showConfirmModal(data.plan);
                break;

            case "cancel_confirm":
                hideConfirmModal();
                break;
        }
    }

    // --- RENDER SCREENSHOT ---
    function loadLatestScreenshot() {
        noCaptureOverlay.style.display = "none";
        canvas.style.display = "block";
        
        screenshotImg.onload = function() {
            // Adjust canvas visual resolution
            canvas.width = screenshotImg.naturalWidth;
            canvas.height = screenshotImg.naturalHeight;
            drawCanvas();
        };
        screenshotImg.onerror = function() {
            log("No se pudo cargar la captura del backend.", "error");
            noCaptureOverlay.style.display = "flex";
            canvas.style.display = "none";
        };
        // Add timestamp to prevent browser cache
        screenshotImg.src = `/api/screenshot/latest?t=${Date.now()}`;
    }

    function drawCanvas() {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
        // Draw the main image
        ctx.drawImage(screenshotImg, 0, 0);

        // Draw saved region overlay if exists and not drawing
        if (currentRegion && !isDrawing) {
            const [rx, ry, rw, rh] = currentRegion;
            ctx.strokeStyle = "#8B5CF6"; // Purple
            ctx.lineWidth = 3;
            ctx.fillStyle = "rgba(139, 92, 246, 0.1)";
            ctx.fillRect(rx, ry, rw, rh);
            ctx.strokeRect(rx, ry, rw, rh);
            
            // Draw text
            ctx.fillStyle = "#8B5CF6";
            ctx.font = "bold 14px sans-serif";
            ctx.fillText("Región activa", rx + 5, ry + 20);
        }

        // Draw active drag box if drawing
        if (isDrawing) {
            const rx = Math.min(startX, curX);
            const ry = Math.min(startY, curY);
            const rw = Math.abs(startX - curX);
            const rh = Math.abs(startY - curY);

            ctx.strokeStyle = "#00F0FF"; // Cyan
            ctx.lineWidth = 2.5;
            ctx.fillStyle = "rgba(0, 240, 255, 0.15)";
            ctx.fillRect(rx, ry, rw, rh);
            ctx.strokeRect(rx, ry, rw, rh);
        }
    }

    // --- CANVAS DRAG REGION SELECTION ---
    function getCanvasCoords(e) {
        const rect = canvas.getBoundingClientRect();
        
        // Scaled coordinates mapping natural resolution with client display layout
        const scaleX = canvas.width / rect.width;
        const scaleY = canvas.height / rect.height;
        
        const clientX = e.clientX - rect.left;
        const clientY = e.clientY - rect.top;
        
        return {
            x: Math.round(clientX * scaleX),
            y: Math.round(clientY * scaleY)
        };
    }

    canvas.addEventListener("mousedown", (e) => {
        if (isLoopRunning) return; // Disable drawing if automated solve is running
        if (e.button !== 0) return; // Only left-click
        
        const coords = getCanvasCoords(e);
        startX = coords.x;
        startY = coords.y;
        curX = coords.x;
        curY = coords.y;
        isDrawing = true;
    });

    canvas.addEventListener("mousemove", (e) => {
        if (!isDrawing) return;
        const coords = getCanvasCoords(e);
        curX = coords.x;
        curY = coords.y;
        drawCanvas();
    });

    canvas.addEventListener("mouseup", (e) => {
        if (!isDrawing) return;
        isDrawing = false;
        
        const coords = getCanvasCoords(e);
        curX = coords.x;
        curY = coords.y;
        
        const rx = Math.min(startX, curX);
        const ry = Math.min(startY, curY);
        const rw = Math.abs(startX - curX);
        const rh = Math.abs(startY - curY);

        // Don't save tiny clicks
        if (rw > 10 && rh > 10) {
            currentRegion = [rx, ry, rw, rh];
            regionBadge.textContent = `Región: ${rx},${ry},${rw},${rh}`;
            log(`Región marcada en canvas: [x: ${rx}, y: ${ry}, w: ${rw}, h: ${rh}]`, "system");
            
            // Save to backend config
            postConfig({ region: currentRegion });
        } else {
            drawCanvas(); // Reset
        }
    });

    // --- SYSTEM STATUS SYNC ---
    function checkSystemStatus() {
        fetch("/api/status")
            .then(res => res.json())
            .then(status => {
                // Update indicator status pills
                updateStatusPill(statusOllama, status.ollama_available, status.ollama_available ? "Ollama: Online" : "Ollama: Offline");
                updateStatusPill(statusTesseract, status.tesseract_available, status.tesseract_available ? "Tesseract: Ready" : "Tesseract: Error");
                
                isLoopRunning = status.loop_running;
                updateLoopPill(isLoopRunning);
                
                // Populate models selector
                if (status.ollama_models && status.ollama_models.length > 0) {
                    const currentModelValue = formModel.value;
                    formModel.innerHTML = "";
                    status.ollama_models.forEach(model => {
                        const opt = document.createElement("option");
                        opt.value = model;
                        opt.textContent = model;
                        if (model === currentModelValue || model === status.config.model) {
                            opt.selected = true;
                        }
                        formModel.appendChild(opt);
                    });
                }

                if (status.pending_confirm) {
                    // Trigger modal fetch if backend is waiting
                    // Since backend has it, we can query last run info
                    if (status.last_run && status.last_run.click_plan) {
                        showConfirmModal(status.last_run.click_plan);
                    }
                }
            })
            .catch(err => {
                console.error("Status error:", err);
                updateStatusPill(statusOllama, false, "Server connection failed");
                updateStatusPill(statusTesseract, false, "Server connection failed");
            });
    }

    function updateStatusPill(pill, isOk, text) {
        const ind = pill.querySelector(".indicator");
        const txt = pill.querySelector(".text");
        
        ind.className = "indicator " + (isOk ? "green" : "red");
        txt.textContent = text;
    }

    function updateLoopPill(running) {
        const ind = statusLoop.querySelector(".indicator");
        const txt = statusLoop.querySelector(".text");
        
        if (running) {
            ind.className = "indicator green";
            txt.textContent = "Bucle: On";
            btnStartLoop.disabled = true;
            btnStopLoop.disabled = false;
            btnRunOnce.disabled = true;
        } else {
            ind.className = "indicator gray";
            txt.textContent = "Bucle: Off";
            btnStartLoop.disabled = false;
            btnStopLoop.disabled = true;
            btnRunOnce.disabled = false;
        }
    }

    // --- FORM CONFIGURE ACTIONS ---
    function syncConfigToForm(config) {
        formOllamaHost.value = config.ollama_host;
        formLang.value = config.lang;
        formPsm.value = config.psm;
        formTesseractCmd.value = config.tesseract_cmd;
        
        formClick.checked = config.click;
        formConfirm.checked = config.confirm;
        formSafeMode.checked = !config.i_am_authorized;
        
        formMinClickScore.value = config.min_click_score;
        valMinClickScore.textContent = config.min_click_score;
        
        formInterval.value = config.interval;
        valInterval.textContent = config.interval + "s";

        formAutoScroll.checked = config.auto_scroll || false;
        formScrollAmount.value = config.scroll_amount !== undefined ? config.scroll_amount : -300;
        formScrollDelay.value = config.scroll_delay !== undefined ? config.scroll_delay : 1.0;

        currentRegion = config.region;
        if (currentRegion) {
            const [rx, ry, rw, rh] = currentRegion;
            regionBadge.textContent = `Región: ${rx},${ry},${rw},${rh}`;
        } else {
            regionBadge.textContent = "Región: Completa";
        }
        
        if (screenshotImg.src) {
            drawCanvas(); // Re-render canvas borders if configuration changes
        }
    }

    function readFormConfig() {
        return {
            ollama_host: formOllamaHost.value,
            model: formModel.value,
            lang: formLang.value,
            psm: parseInt(formPsm.value),
            tesseract_cmd: formTesseractCmd.value,
            click: formClick.checked,
            confirm: formConfirm.checked,
            i_am_authorized: !formSafeMode.checked,
            min_click_score: parseFloat(formMinClickScore.value),
            interval: parseFloat(formInterval.value),
            auto_scroll: formAutoScroll.checked,
            scroll_amount: parseInt(formScrollAmount.value),
            scroll_delay: parseFloat(formScrollDelay.value)
        };
    }

    function postConfig(configData) {
        return fetch("/api/config", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(configData)
        })
        .then(res => res.json())
        .then(data => {
            if (data.success) {
                checkSystemStatus();
            } else {
                log("Error al guardar configuración.", "error");
            }
        })
        .catch(err => {
            log(`Error de red al guardar config: ${err.message}`, "error");
        });
    }

    // --- DISPLAY DETAILED SOLVER INFO ---
    function displayRunResults(data) {
        resultQuestion.textContent = data.question || "[Pregunta vacía o no detectada]";
        
        resultOptions.innerHTML = "";
        if (data.options && data.options.length > 0) {
            data.options.forEach(opt => {
                const li = document.createElement("li");
                li.textContent = opt;
                resultOptions.appendChild(li);
            });
        } else {
            const li = document.createElement("li");
            li.className = "placeholder";
            li.textContent = "Sin opciones detectadas";
            resultOptions.appendChild(li);
        }

        if (data.answer) {
            resultAnswer.textContent = data.answer.answer || "-";
            const conf = Math.round(data.answer.confidence * 100);
            resultConfidence.textContent = `${conf}%`;
            
            // Adjust badge color based on confidence
            if (conf >= 80) resultConfidence.style.backgroundColor = "var(--color-success-bg)";
            else if (conf >= 50) resultConfidence.style.backgroundColor = "var(--color-warning-bg)";
            else resultConfidence.style.backgroundColor = "var(--color-danger-bg)";
            
            resultReason.textContent = data.answer.reason || "-";
            aiAnswerBox.style.display = "flex";
        }

        if (data.click_plan) {
            planText.textContent = data.click_plan.target_text;
            planCoords.textContent = `(${data.click_plan.x}, ${data.click_plan.y})`;
            planScore.textContent = Math.round(data.click_plan.score * 100) + "%";
            planMode.textContent = data.click_plan.dry_run ? "Simulado (Modo seguro)" : "Real (Autorizado)";
            
            if (data.click_plan.dry_run) {
                planMode.style.color = "var(--color-danger)";
            } else {
                planMode.style.color = "var(--color-success)";
            }
        } else {
            planText.textContent = "-";
            planCoords.textContent = "-";
            planScore.textContent = "-";
            planMode.textContent = "-";
            planMode.style.color = "inherit";
        }
    }

    // --- EVENT BINDINGS FOR ACTIONS ---
    formMinClickScore.addEventListener("input", (e) => {
        valMinClickScore.textContent = e.target.value;
    });

    formInterval.addEventListener("input", (e) => {
        valInterval.textContent = e.target.value + "s";
    });

    btnSaveConfig.addEventListener("click", () => {
        const conf = readFormConfig();
        postConfig(conf).then(() => log("Configuración del formulario guardada.", "success"));
    });

    btnRefreshModels.addEventListener("click", () => {
        log("Actualizando lista de modelos Ollama...", "system");
        checkSystemStatus();
    });

    btnRunOnce.addEventListener("click", () => {
        if (isLoopRunning) return;
        log("Ejecutando solve una vez...", "info");
        btnRunOnce.disabled = true;
        
        fetch("/api/run", { method: "POST" })
            .then(res => res.json())
            .then(data => {
                btnRunOnce.disabled = false;
                if (!data.success) {
                    log(`Fallo en el solver: ${data.error}`, "error");
                }
            })
            .catch(err => {
                btnRunOnce.disabled = false;
                log(`Error de red: ${err.message}`, "error");
            });
    });

    btnStartLoop.addEventListener("click", () => {
        log("Petición para iniciar bucle continuo...", "info");
        fetch("/api/loop/start", { method: "POST" })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    isLoopRunning = true;
                    updateLoopPill(true);
                }
            });
    });

    btnStopLoop.addEventListener("click", () => {
        log("Petición para detener bucle continuo...", "info");
        fetch("/api/loop/stop", { method: "POST" })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    isLoopRunning = false;
                    updateLoopPill(false);
                }
            });
    });

    btnClearRegion.addEventListener("click", () => {
        currentRegion = null;
        regionBadge.textContent = "Región: Completa";
        log("Región de captura limpia (usando pantalla completa).", "system");
        postConfig({ region: null });
    });

    btnCapture.addEventListener("click", () => {
        log("Solicitando nueva captura de pantalla...", "info");
        fetch("/api/screenshot/capture", { method: "POST" });
    });

    btnClearConsole.addEventListener("click", () => {
        consoleOutput.innerHTML = "";
        log("Consola limpia.", "system");
    });

    btnToggleViewer.addEventListener("click", () => {
        const viewerCard = document.querySelector(".viewer-card");
        if (viewerCard.classList.contains("show-in-mini")) {
            viewerCard.classList.remove("show-in-mini");
            btnToggleViewer.textContent = "Ver Pantalla";
            log("Visor de pantalla colapsado.", "system");
        } else {
            viewerCard.classList.add("show-in-mini");
            btnToggleViewer.textContent = "Ocultar Pantalla";
            log("Visor de pantalla expandido.", "system");
            // Trigger redrawing just in case
            setTimeout(() => {
                if (screenshotImg.src) drawCanvas();
            }, 100);
        }
    });

    // --- MANUAL CONFIRM MODAL ACTIONS ---
    function showConfirmModal(plan) {
        modalPlanText.textContent = plan.target_text;
        modalPlanCoords.textContent = `(${plan.x}, ${plan.y})`;
        modalPlanScore.textContent = Math.round(plan.score * 100) + "%";
        confirmModal.classList.add("active");
    }

    function hideConfirmModal() {
        confirmModal.classList.remove("active");
    }

    btnModalCancel.addEventListener("click", () => {
        hideConfirmModal();
        fetch("/api/confirm", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ approved: false })
        });
    });

    btnModalApprove.addEventListener("click", () => {
        hideConfirmModal();
        fetch("/api/confirm", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ approved: true })
        });
    });

    // --- COMMAND BAR PALETTE (CMD+K) ---
    btnCmdTrigger.addEventListener("click", () => {
        openCommandBar();
    });

    btnCloseCmdBar.addEventListener("click", () => {
        closeCommandBar();
    });

    function openCommandBar() {
        cmdInput.value = "";
        selectedCmdIndex = 0;
        filterCommands("");
        cmdBar.showModal();
        setTimeout(() => cmdInput.focus(), 50);
    }

    function closeCommandBar() {
        cmdBar.close();
    }

    cmdInput.addEventListener("input", (e) => {
        filterCommands(e.target.value);
    });

    function filterCommands(query) {
        const cleanQuery = query.toLowerCase().trim();
        
        if (cleanQuery === "") {
            filteredCommands = [...commandsList];
        } else {
            filteredCommands = commandsList.filter(cmd => 
                cmd.name.toLowerCase().includes(cleanQuery) || 
                cmd.desc.toLowerCase().includes(cleanQuery)
            );
        }
        
        selectedCmdIndex = 0;
        renderCommandResults();
    }

    function renderCommandResults() {
        cmdResults.innerHTML = "";
        
        if (filteredCommands.length === 0) {
            const div = document.createElement("div");
            div.style.padding = "1rem";
            div.style.color = "var(--text-muted)";
            div.style.textAlign = "center";
            div.textContent = "No se encontraron comandos";
            cmdResults.appendChild(div);
            return;
        }

        filteredCommands.forEach((cmd, idx) => {
            const item = document.createElement("div");
            item.className = `cmd-item ${idx === selectedCmdIndex ? "active" : ""}`;
            
            item.innerHTML = `
                <div class="cmd-item-left">
                    <span class="cmd-item-icon">${cmd.icon}</span>
                    <div class="cmd-item-info">
                        <span class="cmd-item-name">${cmd.name}</span>
                        <span class="cmd-item-desc">${cmd.desc}</span>
                    </div>
                </div>
                ${cmd.shortcut ? `<span class="cmd-item-shortcut">${cmd.shortcut}</span>` : ""}
            `;

            item.addEventListener("click", () => {
                selectedCmdIndex = idx;
                executeSelectedCommand();
            });

            cmdResults.appendChild(item);
        });

        // Ensure selected item is scrolled into view
        const activeItem = cmdResults.querySelector(".cmd-item.active");
        if (activeItem) {
            activeItem.scrollIntoView({ block: "nearest" });
        }
    }

    function executeSelectedCommand() {
        if (filteredCommands.length === 0) return;
        const cmd = filteredCommands[selectedCmdIndex];
        
        log(`Ejecutando comando: ${cmd.name}`, "system");
        closeCommandBar();
        
        switch (cmd.name) {
            case "/solve":
                btnRunOnce.click();
                break;
            case "/loop start":
                btnStartLoop.click();
                break;
            case "/loop stop":
                btnStopLoop.click();
                break;
            case "/click on":
                formClick.checked = true;
                postConfig({ click: true }).then(() => log("Clic automático activado.", "success"));
                break;
            case "/click off":
                formClick.checked = false;
                postConfig({ click: false }).then(() => log("Clic automático desactivado.", "warning"));
                break;
            case "/confirm on":
                formConfirm.checked = true;
                postConfig({ confirm: true }).then(() => log("Confirmación de clic activada.", "success"));
                break;
            case "/confirm off":
                formConfirm.checked = false;
                postConfig({ confirm: false }).then(() => log("Confirmación de clic desactivada.", "warning"));
                break;
            case "/screenshot":
                btnCapture.click();
                break;
            case "/region clear":
                btnClearRegion.click();
                break;
            case "/scroll down":
                log("Simulando scroll manual hacia abajo...", "info");
                fetch("/api/scroll", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ amount: parseInt(formScrollAmount.value) })
                });
                break;
            case "/scroll up":
                log("Simulando scroll manual hacia arriba...", "info");
                fetch("/api/scroll", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ amount: -parseInt(formScrollAmount.value) })
                });
                break;
            case "/scroll auto on":
                formAutoScroll.checked = true;
                postConfig({ auto_scroll: true }).then(() => log("Scroll automático activado.", "success"));
                break;
            case "/scroll auto off":
                formAutoScroll.checked = false;
                postConfig({ auto_scroll: false }).then(() => log("Scroll automático desactivado.", "warning"));
                break;
            case "/status":
                checkSystemStatus();
                log("Estado de servicios solicitado al backend.", "info");
                break;
            case "/help":
                log("Comandos disponibles en Vision Bot:", "info");
                commandsList.forEach(c => {
                    log(`${c.name} - ${c.desc}`, "system");
                });
                break;
        }
    }

    // Keyboard navigation in dialog cmd inputs
    cmdInput.addEventListener("keydown", (e) => {
        if (e.key === "ArrowDown") {
            e.preventDefault();
            selectedCmdIndex = (selectedCmdIndex + 1) % filteredCommands.length;
            renderCommandResults();
        } else if (e.key === "ArrowUp") {
            e.preventDefault();
            selectedCmdIndex = (selectedCmdIndex - 1 + filteredCommands.length) % filteredCommands.length;
            renderCommandResults();
        } else if (e.key === "Enter") {
            e.preventDefault();
            executeSelectedCommand();
        } else if (e.key === "Escape") {
            closeCommandBar();
        }
    });

    // Global Key Listener
    window.addEventListener("keydown", (e) => {
        // Ctrl+K or Cmd+K to trigger Command Bar
        if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
            e.preventDefault();
            if (cmdBar.open) {
                closeCommandBar();
            } else {
                openCommandBar();
            }
        }
        
        // Ctrl+Enter to trigger a solve step
        if ((e.ctrlKey || e.metaKey) && e.key === "Enter") {
            e.preventDefault();
            if (!isLoopRunning) {
                btnRunOnce.click();
            }
        }
    });

    // Close on click outside modal container
    cmdBar.addEventListener("click", (e) => {
        const rect = cmdBar.getBoundingClientRect();
        const isInDialog = (rect.top <= e.clientY && e.clientY <= rect.top + rect.height
          && rect.left <= e.clientX && e.clientX <= rect.left + rect.width);
        if (!isInDialog) {
            closeCommandBar();
        }
    });

    // --- BOOTSTRAP ---
    initWebSocket();
});
