let currentAttempt = null;
let attemptQuestions = [];
let activeQuestionIndex = 0;
let examTimerInterval = null;
let reviewMarked = {}; // Maps question_id -> boolean
let studentSocket = null;
let isAttemptFinished = false;

// Offline Save Queue
let offlineQueue = [];

// Load Available Exams
async function loadStudentDashboard() {
    try {
        const exams = await fetchApi('/api/student/exams');
        const listEl = document.getElementById('student-exam-list');
        listEl.innerHTML = '';
        
        if (exams.length === 0) {
            listEl.innerHTML = `
                <div class="glass text-center p-3 col-6" style="margin: 0 auto; grid-column: 1/-1;">
                    <p class="subtitle" style="margin-bottom: 0;">No exams are currently available.</p>
                </div>
            `;
            return;
        }
        
        exams.forEach(exam => {
            const card = document.createElement('div');
            card.className = 'exam-card glass';
            
            let actionBtnHtml = '';
            let statusBadge = '';
            
            // Format start/end times
            const startTimeStr = exam.start_time ? new Date(exam.start_time).toLocaleString() : 'N/A';
            
            if (exam.attempt_id) {
                if (exam.attempt_status === 'active') {
                    statusBadge = '<span class="badge badge-warning">Active</span>';
                    actionBtnHtml = `<button class="btn btn-primary btn-block" onclick="resumeAttempt(${exam.attempt_id})">Resume Exam</button>`;
                } else {
                    statusBadge = '<span class="badge badge-success">Attempted</span>';
                    actionBtnHtml = `<button class="btn btn-outline btn-block" onclick="viewResult(${exam.attempt_id})">View Result</button>`;
                }
            } else {
                if (exam.status === 'live') {
                    statusBadge = '<span class="badge badge-info">Live</span>';
                    actionBtnHtml = `<button class="btn btn-primary btn-block" onclick="startAttemptPrompt(${exam.id}, '${exam.title}')">Start Exam</button>`;
                } else {
                    statusBadge = '<span class="badge badge-danger">Ended</span>';
                    actionBtnHtml = `<button class="btn btn-outline btn-block" disabled>Exam Ended</button>`;
                }
            }
            
            card.innerHTML = `
                <div style="display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 0.5rem;">
                    <h3>${exam.title}</h3>
                    ${statusBadge}
                </div>
                <p class="exam-card-description">${exam.description || 'No description provided.'}</p>
                <div class="exam-card-meta">
                    <div class="meta-item">
                        <span class="lbl">Duration</span>
                        <span class="val">${exam.duration} mins</span>
                    </div>
                    <div class="meta-item">
                        <span class="lbl">Total Marks</span>
                        <span class="val">${exam.total_marks} pts</span>
                    </div>
                    <div class="meta-item" style="grid-column: span 2;">
                        <span class="lbl">Start Time</span>
                        <span class="val">${startTimeStr}</span>
                    </div>
                </div>
                ${actionBtnHtml}
            `;
            listEl.appendChild(card);
        });
        
        // Handle pending URL-shared exam redirects
        const targetExamId = localStorage.getItem('redirect_exam_id');
        if (targetExamId) {
            localStorage.removeItem('redirect_exam_id');
            const targetExam = exams.find(e => e.id == targetExamId);
            if (targetExam) {
                if (targetExam.attempt_id) {
                    if (targetExam.attempt_status === 'active') {
                        resumeAttempt(targetExam.attempt_id);
                    } else {
                        showToast(`You have already attempted and submitted "${targetExam.title}".`, 'info');
                        viewResult(targetExam.attempt_id);
                    }
                } else {
                    if (targetExam.status === 'live') {
                        startAttemptPrompt(targetExam.id, targetExam.title);
                    } else {
                        showToast(`The exam "${targetExam.title}" is not active yet.`, 'warning');
                    }
                }
            } else {
                showToast("The shared exam is not available or is not currently active.", "warning");
            }
        }
    } catch (error) {
        showToast(error.message, 'danger');
    }
}

// Prompt to Start
function startAttemptPrompt(examId, examTitle) {
    showConfirm(
        'Start Examination',
        `Are you ready to start "${examTitle}"? Once started, you must complete it under fullscreen security rules.`,
        () => startAttempt(examId)
    );
}

// Start New Attempt
async function startAttempt(examId) {
    try {
        const data = await fetchApi(`/api/student/exams/${examId}/attempt`, {
            method: 'POST'
        });
        
        resumeAttempt(data.attempt_id);
    } catch (error) {
        showToast(error.message, 'danger');
    }
}

// Resume/Load active attempt
async function resumeAttempt(attemptId) {
    try {
        const data = await fetchApi(`/api/student/attempts/${attemptId}`);
        
        if (data.attempt.status !== 'active') {
            // Already submitted, show results
            viewResult(attemptId);
            return;
        }
        
        currentAttempt = data.attempt;
        attemptQuestions = data.questions;
        activeQuestionIndex = 0;
        isAttemptFinished = false;
        reviewMarked = {};
        
        // Show Exam workspace
        showView('student-exam');
        document.getElementById('student-exam-title').textContent = currentAttempt.exam_title;
        document.getElementById('candidate-name').textContent = currentUser.name;
        
        // Render Navigator and first question
        renderNavigator();
        renderQuestion();
        
        // Setup Fullscreen check
        setupFullscreenSafety();
        
        // Setup timers
        startCountdown(data.remaining_seconds);
        
        // Connect websocket for live ended
        connectStudentSocket(attemptId);
        
    } catch (error) {
        showToast(error.message, 'danger');
    }
}

// Render Question navigator grid
function renderNavigator() {
    const grid = document.getElementById('question-grid');
    grid.innerHTML = '';
    
    attemptQuestions.forEach((q, index) => {
        const item = document.createElement('div');
        item.className = 'grid-num';
        item.textContent = index + 1;
        
        if (index === activeQuestionIndex) {
            item.classList.add('current');
        }
        
        if (q.selected_option_id !== null) {
            item.classList.add('answered');
        }
        
        if (reviewMarked[q.question_id]) {
            item.classList.add('review');
        }
        
        item.onclick = () => {
            activeQuestionIndex = index;
            renderQuestion();
            updateNavigatorActiveState();
        };
        
        grid.appendChild(item);
    });
}

function updateNavigatorActiveState() {
    const gridItems = document.getElementById('question-grid').children;
    for (let i = 0; i < gridItems.length; i++) {
        gridItems[i].classList.remove('current');
        if (i === activeQuestionIndex) {
            gridItems[i].classList.add('current');
        }
    }
}

// Render Active Question
function renderQuestion() {
    if (attemptQuestions.length === 0) return;
    
    const q = attemptQuestions[activeQuestionIndex];
    
    document.getElementById('student-exam-meta').textContent = `Question ${activeQuestionIndex + 1} of ${attemptQuestions.length}`;
    document.getElementById('q-num-badge').textContent = `Question ${activeQuestionIndex + 1}`;
    document.getElementById('q-marks-badge').textContent = `Marks: ${q.marks}`;
    document.getElementById('question-text').textContent = q.question_text;
    
    // Render Image if available
    const imgContainer = document.getElementById('question-image-container');
    const imgEl = document.getElementById('question-image');
    if (q.image) {
        imgEl.src = q.image;
        imgContainer.classList.remove('hidden');
    } else {
        imgContainer.classList.add('hidden');
    }
    
    // Render Options
    const optContainer = document.getElementById('options-container');
    optContainer.innerHTML = '';
    
    const labels = ['A', 'B', 'C', 'D'];
    q.options.forEach((opt, idx) => {
        const btn = document.createElement('button');
        btn.className = 'option-btn';
        if (q.selected_option_id === opt.id) {
            btn.classList.add('selected');
        }
        
        let optImgHtml = '';
        if (opt.option_image) {
            optImgHtml = `
                <div class="option-image-wrapper" style="margin-top: 0.5rem; text-align: left;">
                    <img src="${opt.option_image}" alt="Option ${labels[idx]}" style="max-height: 150px; max-width: 100%; border-radius: 4px; border: 1px solid rgba(255,255,255,0.1);">
                </div>
            `;
        }
        
        btn.innerHTML = `
            <span class="option-label">${labels[idx]}</span>
            <div style="flex: 1; display: flex; flex-direction: column;">
                <span class="option-text">${opt.option_text}</span>
                ${optImgHtml}
            </div>
        `;
        
        btn.onclick = () => selectOption(q.question_id, opt.id, btn);
        optContainer.appendChild(btn);
    });
    
    // Toggle review button text
    const reviewBtn = document.getElementById('mark-review-btn');
    if (reviewMarked[q.question_id]) {
        reviewBtn.textContent = 'Unmark Review';
    } else {
        reviewBtn.textContent = 'Mark for Review';
    }
}

// Toggle Review status locally
document.getElementById('mark-review-btn').onclick = () => {
    const q = attemptQuestions[activeQuestionIndex];
    reviewMarked[q.question_id] = !reviewMarked[q.question_id];
    
    renderQuestion();
    renderNavigator();
};

// Select Option
async function selectOption(questionId, optionId, btnElement) {
    // UI update
    const btns = document.querySelectorAll('.option-btn');
    btns.forEach(btn => btn.classList.remove('selected'));
    btnElement.classList.add('selected');
    
    // Save locally
    attemptQuestions[activeQuestionIndex].selected_option_id = optionId;
    renderNavigator();
    
    // Sync to Server
    saveAnswerToServer(questionId, optionId);
}

async function saveAnswerToServer(questionId, optionId) {
    if (navigator.onLine) {
        try {
            await fetchApi(`/api/student/attempts/${currentAttempt.id}/save-answer`, {
                method: 'POST',
                body: { question_id: questionId, selected_option_id: optionId }
            });
            document.getElementById('exam-conn-status').textContent = 'Answers Synced';
        } catch (error) {
            showToast('Unable to sync answer. Saved locally.', 'warning');
            queueOfflineAnswer(questionId, optionId);
        }
    } else {
        document.getElementById('exam-conn-status').textContent = 'Offline (Saved Locally)';
        queueOfflineAnswer(questionId, optionId);
    }
}

function queueOfflineAnswer(questionId, optionId) {
    // Remove if already exists in offline queue to prevent duplicates
    offlineQueue = offlineQueue.filter(item => item.question_id !== questionId);
    offlineQueue.push({ question_id: questionId, selected_option_id: optionId });
}

// Navigation Controls
document.getElementById('prev-q-btn').onclick = () => {
    if (activeQuestionIndex > 0) {
        activeQuestionIndex--;
        renderQuestion();
        updateNavigatorActiveState();
    }
};

document.getElementById('save-next-btn').onclick = () => {
    if (activeQuestionIndex < attemptQuestions.length - 1) {
        activeQuestionIndex++;
        renderQuestion();
        updateNavigatorActiveState();
    } else {
        showToast('You are on the last question.', 'info');
    }
};

// Manual Submission
document.getElementById('submit-exam-btn').onclick = () => {
    const answeredCount = attemptQuestions.filter(q => q.selected_option_id !== null).length;
    showConfirm(
        'Submit Examination',
        `You have answered ${answeredCount} of ${attemptQuestions.length} questions. Are you sure you want to finalize your submission?`,
        () => finalizeSubmission('manual')
    );
};

async function finalizeSubmission(type, reason = null) {
    if (isAttemptFinished) return;
    isAttemptFinished = true;
    
    clearInterval(examTimerInterval);
    closeFullscreen();
    cleanupAntiCheat();
    
    if (studentSocket) {
        studentSocket.close();
    }
    
    // Sync offline queue if online
    if (navigator.onLine && offlineQueue.length > 0) {
        try {
            for (let item of offlineQueue) {
                await fetchApi(`/api/student/attempts/${currentAttempt.id}/save-answer`, {
                    method: 'POST',
                    body: item
                });
            }
            offlineQueue = [];
        } catch (e) {
            console.error('Failed to sync remaining offline queue:', e);
        }
    }
    
    try {
        await fetchApi(`/api/student/attempts/${currentAttempt.id}/submit`, {
            method: 'POST',
            body: { submission_type: type, violation_reason: reason }
        });
        
        showToast('Exam submitted successfully', 'success');
        viewResult(currentAttempt.id);
    } catch (error) {
        showToast('Error during final submission: ' + error.message, 'danger');
        // Let them go to results dashboard since backend auto-evaluates on fetch anyway
        viewResult(currentAttempt.id);
    }
}

// Countdown Timer
function startCountdown(secondsLeft) {
    if (examTimerInterval) clearInterval(examTimerInterval);
    
    const timerEl = document.getElementById('exam-timer');
    timerEl.classList.remove('timer-warn', 'timer-danger');
    
    const updateDisplay = (sec) => {
        const hrs = Math.floor(sec / 3600);
        const mins = Math.floor((sec % 3600) / 60);
        const secs = sec % 60;
        
        timerEl.textContent = `${String(hrs).padStart(2, '0')}:${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
        
        // Warnings
        if (sec <= 60) {
            timerEl.className = 'timer-val timer-danger';
        } else if (sec <= 300) {
            timerEl.className = 'timer-val timer-warn';
        }
    };
    
    updateDisplay(secondsLeft);
    
    examTimerInterval = setInterval(() => {
        secondsLeft--;
        if (secondsLeft <= 0) {
            clearInterval(examTimerInterval);
            timerEl.textContent = "00:00:00";
            showToast('Time limit exceeded. Submitting examination.', 'warning');
            finalizeSubmission('time_expired', 'Timer expired.');
        } else {
            updateDisplay(secondsLeft);
        }
    }, 1000);
}

// Anti Cheating Fullscreen & Visibility setup
const fsOverlay = document.getElementById('fullscreen-overlay');
const enterFsBtn = document.getElementById('enter-fullscreen-btn');

function setupFullscreenSafety() {
    fsOverlay.classList.remove('hidden');
    enterFsBtn.onclick = () => {
        enterFullscreen();
    };
}

function enterFullscreen() {
    const el = document.documentElement;
    const requestMethod = el.requestFullscreen || el.mozRequestFullScreen || el.webkitRequestFullScreen || el.msRequestFullscreen;
    
    if (requestMethod) {
        requestMethod.call(el).then(() => {
            fsOverlay.classList.add('hidden');
            startAntiCheatTracking();
        }).catch(err => {
            showToast('Fullscreen denied. Fullscreen mode is mandatory to write the exam.', 'danger');
        });
    } else {
        // Browser does not support Fullscreen
        fsOverlay.classList.add('hidden');
        startAntiCheatTracking();
    }
}

function closeFullscreen() {
    try {
        if (document.fullscreenElement) {
            document.exitFullscreen();
        }
    } catch (e) {}
}

// Listeners storage for cleanup
const antiCheatListeners = {};

function startAntiCheatTracking() {
    // 1. Visibility change listener (Tab Switch / App Switch / Window Minimize)
    antiCheatListeners.visibility = () => {
        if (document.visibilityState === 'hidden') {
            triggerViolation('page_hidden');
        }
    };
    document.addEventListener('visibilitychange', antiCheatListeners.visibility);
    
    // 2. Focus / Blur listeners (Leaving the window focus, clicking inspector tools, etc.)
    antiCheatListeners.blur = () => {
        triggerViolation('tab_switch');
    };
    window.addEventListener('blur', antiCheatListeners.blur);
    
    // 3. Fullscreen exit listener
    antiCheatListeners.fullscreen = () => {
        if (!document.fullscreenElement && !isAttemptFinished) {
            triggerViolation('fullscreen_exit');
        }
    };
    document.addEventListener('fullscreenchange', antiCheatListeners.fullscreen);
}

function cleanupAntiCheat() {
    if (antiCheatListeners.visibility) {
        document.removeEventListener('visibilitychange', antiCheatListeners.visibility);
    }
    if (antiCheatListeners.blur) {
        window.removeEventListener('blur', antiCheatListeners.blur);
    }
    if (antiCheatListeners.fullscreen) {
        document.removeEventListener('fullscreenchange', antiCheatListeners.fullscreen);
    }
    fsOverlay.classList.add('hidden');
}

// Trigger Cheating Violation
async function triggerViolation(type) {
    if (isAttemptFinished) return;
    isAttemptFinished = true;
    
    clearInterval(examTimerInterval);
    cleanupAntiCheat();
    closeFullscreen();
    
    if (studentSocket) studentSocket.close();
    
    let reason = '';
    if (type === 'tab_switch') reason = 'Student left the exam tab or window focus was lost.';
    else if (type === 'page_hidden') reason = 'Student switched to another application or tab (page hidden).';
    else if (type === 'fullscreen_exit') reason = 'Student exited fullscreen mode.';
    
    try {
        // Send violation report
        await fetchApi(`/api/student/attempts/${currentAttempt.id}/violation`, {
            method: 'POST',
            body: { type, details: reason }
        });
        
        // Show result/violated notification page
        alert(`Examination Violation Detected: ${reason}\nYour exam has been automatically submitted and locked.`);
        viewResult(currentAttempt.id);
        
    } catch (error) {
        // Force evaluation view redirect anyway
        viewResult(currentAttempt.id);
    }
}

// Connection Network Listeners
window.addEventListener('online', () => {
    const badge = document.getElementById('connection-badge');
    badge.className = 'badge badge-success';
    badge.textContent = 'Online';
    badge.classList.remove('hidden');
    
    // Sync offline answers queue
    syncOfflineAnswers();
});

window.addEventListener('offline', () => {
    const badge = document.getElementById('connection-badge');
    badge.className = 'badge badge-danger';
    badge.textContent = 'Offline';
    badge.classList.remove('hidden');
});

async function syncOfflineAnswers() {
    if (offlineQueue.length === 0 || !currentAttempt) return;
    
    showToast('Reconnected. Syncing answers...', 'info');
    
    try {
        for (let item of offlineQueue) {
            await fetchApi(`/api/student/attempts/${currentAttempt.id}/save-answer`, {
                method: 'POST',
                body: item
            });
        }
        offlineQueue = [];
        document.getElementById('exam-conn-status').textContent = 'Answers Synced';
        showToast('All answers synced successfully.', 'success');
    } catch (error) {
        console.error('Error syncing offline answers:', error);
    }
}

// WebSocket Connection to receive end notifications
function connectStudentSocket(attemptId) {
    if (studentSocket) studentSocket.close();
    
    const loc = window.location;
    const proto = loc.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${proto}//${loc.host}/ws/student/${attemptId}?token=${localStorage.getItem('token')}`;
    
    studentSocket = new WebSocket(wsUrl);
    
    studentSocket.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.event === 'exam_ended_by_teacher') {
            alert('The teacher has ended this examination.');
            finalizeSubmission('teacher_ended', 'Exam ended by teacher command.');
        }
    };
    
    studentSocket.onclose = () => {
        console.log('Student WebSocket closed');
    };
}

// Results and detailed review
async function viewResult(attemptId) {
    try {
        const data = await fetchApi(`/api/student/attempts/${attemptId}/result`);
        showView('student-result');
        
        document.getElementById('result-exam-title').textContent = data.attempt.exam_title;
        document.getElementById('result-score').textContent = `${data.attempt.score} / ${data.attempt.exam_total_marks}`;
        document.getElementById('result-percentage').textContent = `${data.attempt.percentage}%`;
        
        // Show status based on violation vs submit
        const msgEl = document.getElementById('result-submission-msg');
        const iconEl = document.getElementById('result-icon');
        
        if (data.attempt.status === 'violated') {
            iconEl.textContent = '⚠️';
            msgEl.innerHTML = `<span class="text-danger" style="font-weight: 700;">Submission Violations Detected</span><br>Reason: ${data.attempt.violation_reason || 'Unknown breach'}`;
        } else {
            iconEl.textContent = '🎓';
            msgEl.textContent = 'Your attempt has been successfully evaluated.';
        }
        
        // Stats grid
        document.getElementById('stat-total-q').textContent = data.stats.total;
        document.getElementById('stat-correct-q').textContent = data.stats.correct;
        document.getElementById('stat-incorrect-q').textContent = data.stats.incorrect;
        document.getElementById('stat-unattempted-q').textContent = data.stats.unattempted;
        document.getElementById('stat-time-taken').textContent = data.stats.time_taken;
        document.getElementById('stat-violations').textContent = data.stats.violations_count;
        
        // Set up detailed review button
        const reviewBtn = document.getElementById('review-answers-btn');
        const reviewSection = document.getElementById('detailed-answers-review');
        reviewSection.classList.add('hidden');
        
        reviewBtn.onclick = () => {
            reviewSection.classList.toggle('hidden');
            if (!reviewSection.classList.contains('hidden')) {
                renderDetailedQuestions(data.questions);
            }
        };
        
    } catch (error) {
        showToast(error.message, 'danger');
    }
}

function renderDetailedQuestions(questions) {
    const container = document.getElementById('review-questions-container');
    container.innerHTML = '';
    
    questions.forEach((q, idx) => {
        const card = document.createElement('div');
        card.className = 'review-q-item glass';
        
        let statusBadge = '';
        if (q.result_status === 'correct') {
            statusBadge = '<span class="badge badge-success review-q-status">Correct</span>';
        } else if (q.result_status === 'incorrect') {
            statusBadge = '<span class="badge badge-danger review-q-status">Incorrect</span>';
        } else {
            statusBadge = '<span class="badge badge-warning review-q-status">Unattempted</span>';
        }
        
        // Render options list
        let optionsHtml = '<div class="review-options">';
        q.options.forEach(opt => {
            let className = 'review-opt';
            // Is it the correct answer?
            const isCorrect = opt.option_text === q.correct_answer;
            // Did student select it?
            const isSelected = opt.id === q.selected_option_id;
            
            if (isCorrect) {
                className += ' correct';
            } else if (isSelected && !isCorrect) {
                className += ' incorrect';
            }
            
            let selectionIndicator = '';
            if (isSelected) selectionIndicator = ' <strong>(Your Answer)</strong>';
            if (isCorrect) selectionIndicator += ' ✓';
            
            let optImgHtml = '';
            if (opt.option_image) {
                optImgHtml = `<br><img src="${opt.option_image}" alt="Option Image" style="max-height: 100px; margin-top: 0.25rem; border-radius: 4px; display: block; border: 1px solid rgba(255,255,255,0.1);">`;
            }
            
            optionsHtml += `<div class="${className}">${opt.option_text}${selectionIndicator}${optImgHtml}</div>`;
        });
        optionsHtml += '</div>';
        
        const explanationHtml = q.explanation ? `
            <div class="review-explanation">
                <strong>Explanation:</strong> ${q.explanation}
            </div>
        ` : '';
        
        card.innerHTML = `
            <div>
                ${statusBadge}
                <h4>Question ${idx + 1}</h4>
            </div>
            <p style="margin-top: 0.5rem; font-size: 1rem;">${q.question_text}</p>
            ${optionsHtml}
            ${explanationHtml}
        `;
        
        container.appendChild(card);
    });
}
