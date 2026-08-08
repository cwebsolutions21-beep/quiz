let activeExamId = null;
let activeQuestionId = null;
let examQuestionsList = [];
let monitorSocket = null;
let monitorInterval = null;
let lastMonitorData = [];

// Load Teacher Dashboard
async function loadTeacherDashboard() {
    try {
        const exams = await fetchApi('/api/exams');
        const tbody = document.getElementById('teacher-exams-tbody');
        tbody.innerHTML = '';
        
        if (exams.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="6" class="text-center p-3">
                        <p class="subtitle" style="margin-bottom: 0;">No exams created yet. Click "Create Exam" to begin.</p>
                    </td>
                </tr>
            `;
            return;
        }
        
        exams.forEach(exam => {
            const tr = document.createElement('tr');
            
            let statusBadge = '';
            let actionButtons = '';
            
            switch (exam.status) {
                case 'draft':
                    statusBadge = '<span class="badge badge-warning">Draft</span>';
                    actionButtons = `
                        <button class="btn btn-primary btn-xs" onclick="updateExamStatus(${exam.id}, 'live')">🚀 Go Live</button>
                        <button class="btn btn-outline btn-xs" onclick="openQuestionsManager(${exam.id})">❓ Questions (${exam.question_count})</button>
                        <button class="btn btn-outline btn-xs" onclick="openEditExamModal(${exam.id})">✏️ Edit</button>
                        <button class="btn btn-outline btn-xs" onclick="copyShareLink(${exam.id}, \`${exam.title.replace(/`/g, '\\`').replace(/\$/g, '\\$')}\`)">🔗 Share Link</button>
                        <button class="btn btn-danger-outline btn-xs" onclick="deleteExamPrompt(${exam.id})">🗑️ Delete</button>
                    `;
                    break;
                case 'scheduled':
                    statusBadge = '<span class="badge badge-info">Scheduled</span>';
                    actionButtons = `
                        <button class="btn btn-primary btn-xs" onclick="updateExamStatus(${exam.id}, 'live')">🚀 Start Exam</button>
                        <button class="btn btn-outline btn-xs" onclick="openQuestionsManager(${exam.id})">❓ Questions (${exam.question_count})</button>
                        <button class="btn btn-outline btn-xs" onclick="openEditExamModal(${exam.id})">✏️ Edit</button>
                        <button class="btn btn-outline btn-xs" onclick="copyShareLink(${exam.id}, \`${exam.title.replace(/`/g, '\\`').replace(/\$/g, '\\$')}\`)">🔗 Share Link</button>
                        <button class="btn btn-danger-outline btn-xs" onclick="deleteExamPrompt(${exam.id})">🗑️ Delete</button>
                    `;
                    break;
                case 'live':
                    statusBadge = '<span class="badge badge-success">Live</span>';
                    actionButtons = `
                        <button class="btn btn-danger btn-xs" onclick="updateExamStatus(${exam.id}, 'ended')">🛑 End Exam</button>
                        <button class="btn btn-primary btn-xs" onclick="openLiveMonitor(${exam.id}, \`${exam.title.replace(/`/g, '\\`').replace(/\$/g, '\\$')}\`)">👁️ Monitor</button>
                        <button class="btn btn-outline btn-xs" onclick="copyShareLink(${exam.id}, \`${exam.title.replace(/`/g, '\\`').replace(/\$/g, '\\$')}\`)">🔗 Share Link</button>
                    `;
                    break;
                case 'ended':
                    statusBadge = '<span class="badge badge-danger">Ended</span>';
                    actionButtons = `
                        <button class="btn btn-outline btn-xs" onclick="openLiveMonitor(${exam.id}, \`${exam.title.replace(/`/g, '\\`').replace(/\$/g, '\\$')}\`)">📊 Results</button>
                        <button class="btn btn-outline btn-xs" onclick="copyShareLink(${exam.id}, \`${exam.title.replace(/`/g, '\\`').replace(/\$/g, '\\$')}\`)">🔗 Share Link</button>
                        <button class="btn btn-danger-outline btn-xs" onclick="deleteExamPrompt(${exam.id})">🗑️ Delete</button>
                    `;
                    break;
            }
            
            tr.innerHTML = `
                <td>
                    <div class="exam-title-row">${exam.title}</div>
                    <div class="exam-desc-row">${exam.description || 'No description'}</div>
                </td>
                <td>${exam.duration} mins</td>
                <td>${exam.total_marks} pts</td>
                <td>${exam.question_count}</td>
                <td>${statusBadge}</td>
                <td>
                    <div style="display: flex; gap: 0.5rem; flex-wrap: wrap;">
                        ${actionButtons}
                    </div>
                </td>
            `;
            tbody.appendChild(tr);
        });
    } catch (error) {
        showToast(error.message, 'danger');
    }
}

// Exam Status Patch
async function updateExamStatus(examId, status) {
    let confirmMsg = `Are you sure you want to change status to "${status}"?`;
    if (status === 'live') {
        confirmMsg = 'Are you sure you want to START this exam? Eligible students will be able to attempt it immediately.';
    } else if (status === 'ended') {
        confirmMsg = 'Are you sure you want to END this exam? All active student sessions will be automatically submitted and locked.';
    }
    
    showConfirm(
        'Change Exam Status',
        confirmMsg,
        async () => {
            try {
                await fetchApi(`/api/exams/${examId}/status`, {
                    method: 'PATCH',
                    body: { status }
                });
                showToast(`Exam is now ${status}`, 'success');
                loadTeacherDashboard();
            } catch (error) {
                showToast(error.message, 'danger');
            }
        }
    );
}

// Delete Exam
function deleteExamPrompt(examId) {
    showConfirm(
        'Delete Examination',
        'Are you sure you want to delete this exam? This will erase all questions and student attempts permanently. This action cannot be undone.',
        async () => {
            try {
                await fetchApi(`/api/exams/${examId}`, { method: 'DELETE' });
                showToast('Exam deleted successfully', 'success');
                loadTeacherDashboard();
            } catch (error) {
                showToast(error.message, 'danger');
            }
        }
    );
}

// Create/Edit Exam Modal CRUD
const examModal = document.getElementById('exam-modal');
const examForm = document.getElementById('exam-form');

function openCreateExamModal() {
    document.getElementById('exam-modal-title').textContent = 'Create New Examination';
    document.getElementById('edit-exam-id').value = '';
    examForm.reset();
    document.getElementById('exam-status').value = 'draft';
    examModal.classList.remove('hidden');
}

async function openEditExamModal(examId) {
    try {
        const exam = await fetchApi(`/api/exams/${examId}`);
        document.getElementById('exam-modal-title').textContent = 'Edit Examination';
        document.getElementById('edit-exam-id').value = exam.id;
        document.getElementById('exam-title').value = exam.title;
        document.getElementById('exam-desc').value = exam.description;
        document.getElementById('exam-duration').value = exam.duration;
        document.getElementById('exam-marks').value = exam.total_marks;
        document.getElementById('exam-negative').value = exam.negative_mark;
        document.getElementById('exam-status').value = exam.status;
        
        examModal.classList.remove('hidden');
    } catch (error) {
        showToast(error.message, 'danger');
    }
}

function closeExamModal() {
    examModal.classList.add('hidden');
}

async function saveExam(e) {
    e.preventDefault();
    const examId = document.getElementById('edit-exam-id').value;
    const payload = {
        title: document.getElementById('exam-title').value,
        description: document.getElementById('exam-desc').value,
        duration: parseInt(document.getElementById('exam-duration').value),
        total_marks: parseFloat(document.getElementById('exam-marks').value),
        negative_mark: parseFloat(document.getElementById('exam-negative').value || 0.0),
        status: document.getElementById('exam-status').value
    };
    
    try {
        if (examId) {
            await fetchApi(`/api/exams/${examId}`, {
                method: 'PUT',
                body: payload
            });
            showToast('Exam updated successfully', 'success');
        } else {
            await fetchApi('/api/exams', {
                method: 'POST',
                body: payload
            });
            showToast('Exam created successfully', 'success');
        }
        closeExamModal();
        loadTeacherDashboard();
    } catch (error) {
        showToast(error.message, 'danger');
    }
}


// ================= QUESTIONS MANAGER (MODAL) =================
const qmanagerModal = document.getElementById('qmanager-modal');
const questionForm = document.getElementById('question-form');

async function openQuestionsManager(examId) {
    activeExamId = examId;
    qmanagerModal.classList.remove('hidden');
    await loadQuestionsList();
    openAddQuestionForm();
}

function closeQManager() {
    qmanagerModal.classList.add('hidden');
    loadTeacherDashboard();
}

async function loadQuestionsList() {
    try {
        const questions = await fetchApi(`/api/exams/${activeExamId}/questions`);
        examQuestionsList = questions;
        
        const listEl = document.getElementById('qmanager-list');
        listEl.innerHTML = '';
        
        questions.forEach((q, index) => {
            const item = document.createElement('div');
            item.className = 'q-list-item';
            item.id = `q-item-${q.id}`;
            item.textContent = `${index + 1}. ${q.question_text}`;
            item.onclick = () => selectQuestion(q);
            listEl.appendChild(item);
        });
    } catch (error) {
        showToast(error.message, 'danger');
    }
}

function openAddQuestionForm() {
    activeQuestionId = null;
    questionForm.reset();
    document.getElementById('question-edit-id').value = '';
    
    // Highlight list item logic
    document.querySelectorAll('.q-list-item').forEach(item => item.classList.remove('active'));
    
    document.getElementById('qmanager-placeholder').classList.add('hidden');
    questionForm.classList.remove('hidden');
    document.getElementById('delete-q-btn').classList.add('hidden');
    resetUploadButtons();
}

function selectQuestion(q) {
    activeQuestionId = q.id;
    document.getElementById('question-edit-id').value = q.id;
    document.getElementById('q-text').value = q.question_text;
    document.getElementById('q-marks').value = q.marks;
    document.getElementById('q-neg-marks').value = q.negative_marks;
    document.getElementById('q-difficulty').value = q.difficulty || 'medium';
    document.getElementById('q-explanation').value = q.explanation || '';
    document.getElementById('q-topic').value = q.topic || '';
    document.getElementById('q-image').value = q.image || '';
    
    // Set options
    const options = q.options || [];
    document.getElementById('q-opt-a').value = (options[0] && options[0].option_text !== '[Option A]') ? options[0].option_text : '';
    document.getElementById('q-opt-a-image').value = options[0] ? (options[0].option_image || '') : '';
    document.getElementById('q-opt-b').value = (options[1] && options[1].option_text !== '[Option B]') ? options[1].option_text : '';
    document.getElementById('q-opt-b-image').value = options[1] ? (options[1].option_image || '') : '';
    document.getElementById('q-opt-c').value = (options[2] && options[2].option_text !== '[Option C]') ? options[2].option_text : '';
    document.getElementById('q-opt-c-image').value = options[2] ? (options[2].option_image || '') : '';
    document.getElementById('q-opt-d').value = (options[3] && options[3].option_text !== '[Option D]') ? options[3].option_text : '';
    document.getElementById('q-opt-d-image').value = options[3] ? (options[3].option_image || '') : '';
    
    // Identify which index matches correct answer text
    let correctLetter = '';
    options.forEach((opt, idx) => {
        if (opt.option_text === q.correct_answer) {
            correctLetter = ['A', 'B', 'C', 'D'][idx];
        }
    });
    
    document.getElementById('q-correct').value = correctLetter;
    
    // Active styling on sidebar
    document.querySelectorAll('.q-list-item').forEach(item => item.classList.remove('active'));
    const activeItem = document.getElementById(`q-item-${q.id}`);
    if (activeItem) activeItem.classList.add('active');
    
    document.getElementById('qmanager-placeholder').classList.add('hidden');
    questionForm.classList.remove('hidden');
    document.getElementById('delete-q-btn').classList.remove('hidden');
    resetUploadButtons();
}
    
async function saveQuestion(e) {
    e.preventDefault();
    
    // Map correct option value back to original option text
    const correctLetter = document.getElementById('q-correct').value;
    let optA = document.getElementById('q-opt-a').value;
    let optB = document.getElementById('q-opt-b').value;
    let optC = document.getElementById('q-opt-c').value;
    let optD = document.getElementById('q-opt-d').value;
    
    const optAImg = document.getElementById('q-opt-a-image').value;
    const optBImg = document.getElementById('q-opt-b-image').value;
    const optCImg = document.getElementById('q-opt-c-image').value;
    const optDImg = document.getElementById('q-opt-d-image').value;

    // Validate that either text or image is present for all options
    if (!optA && !optAImg) {
        showToast("Please provide either text or an uploaded image for Option A.", "warning");
        return;
    }
    if (!optB && !optBImg) {
        showToast("Please provide either text or an uploaded image for Option B.", "warning");
        return;
    }
    if (!optC && !optCImg) {
        showToast("Please provide either text or an uploaded image for Option C.", "warning");
        return;
    }
    if (!optD && !optDImg) {
        showToast("Please provide either text or an uploaded image for Option D.", "warning");
        return;
    }

    // Apply internal fallback placeholder if text is empty but image is present
    if (!optA) optA = '[Option A]';
    if (!optB) optB = '[Option B]';
    if (!optC) optC = '[Option C]';
    if (!optD) optD = '[Option D]';
    
    let correctText = '';
    if (correctLetter === 'A') correctText = optA;
    else if (correctLetter === 'B') correctText = optB;
    else if (correctLetter === 'C') correctText = optC;
    else if (correctLetter === 'D') correctText = optD;
    
    const payload = {
        question_text: document.getElementById('q-text').value,
        marks: parseFloat(document.getElementById('q-marks').value),
        negative_marks: parseFloat(document.getElementById('q-neg-marks').value || 0.0),
        difficulty: document.getElementById('q-difficulty').value,
        options: [
            { option_text: optA, option_image: optAImg || null },
            { option_text: optB, option_image: optBImg || null },
            { option_text: optC, option_image: optCImg || null },
            { option_text: optD, option_image: optDImg || null }
        ],
        correct_answer: correctText,
        explanation: document.getElementById('q-explanation').value,
        topic: document.getElementById('q-topic').value,
        image: document.getElementById('q-image').value
    };
    
    try {
        if (activeQuestionId) {
            await fetchApi(`/api/exams/${activeExamId}/questions/${activeQuestionId}`, {
                method: 'PUT',
                body: payload
            });
            showToast('Question updated', 'success');
        } else {
            await fetchApi(`/api/exams/${activeExamId}/questions`, {
                method: 'POST',
                body: payload
            });
            showToast('Question added', 'success');
        }
        
        await loadQuestionsList();
        openAddQuestionForm();
    } catch (error) {
        showToast(error.message, 'danger');
    }
}

async function deleteQuestion() {
    if (!activeQuestionId) return;
    
    showConfirm(
        'Delete Question',
        'Are you sure you want to remove this question from the exam?',
        async () => {
            try {
                await fetchApi(`/api/exams/${activeExamId}/questions/${activeQuestionId}`, {
                    method: 'DELETE'
                });
                showToast('Question deleted', 'success');
                await loadQuestionsList();
                openAddQuestionForm();
            } catch (error) {
                showToast(error.message, 'danger');
            }
        }
    );
}

// Question Bank Export/Import JSON helper
function exportQuestions() {
    if (!examQuestionsList || examQuestionsList.length === 0) {
        showToast('No questions to export', 'warning');
        return;
    }
    
    // Structure simple file contents
    const exp = examQuestionsList.map(q => ({
        question_text: q.question_text,
        marks: q.marks,
        negative_marks: q.negative_marks,
        difficulty: q.difficulty,
        correct_answer: q.correct_answer,
        options: (q.options || []).map(o => o.option_text),
        explanation: q.explanation,
        topic: q.topic,
        image: q.image
    }));
    
    const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(exp, null, 2));
    const dlAnchorElem = document.createElement('a');
    dlAnchorElem.setAttribute("href", dataStr);
    dlAnchorElem.setAttribute("download", `exam_${activeExamId}_questions.json`);
    dlAnchorElem.click();
}

function triggerImport() {
    document.getElementById('import-file-input').click();
}

async function importQuestions(e) {
    const file = e.target.files[0];
    if (!file) return;
    
    const reader = new FileReader();
    reader.onload = async (evt) => {
        try {
            let list = JSON.parse(evt.target.result);
            
            // Proactively handle wrapper objects e.g., { "questions": [...] }
            if (!Array.isArray(list) && list && typeof list === 'object' && Array.isArray(list.questions)) {
                list = list.questions;
            }
            
            if (!Array.isArray(list)) {
                throw new Error('File must be a JSON array of questions, or a JSON object containing a "questions" list.');
            }
            
            // Send payload to backend
            const result = await fetchApi('/api/question-bank/import', {
                method: 'POST',
                body: { exam_id: activeExamId, questions: list }
            });
            
            showToast(`Imported ${result.count} questions successfully.`, 'success');
            await loadQuestionsList();
        } catch (err) {
            showToast('Failed to parse or upload file: ' + err.message, 'danger');
        }
    };
    reader.readAsText(file);
    // Reset file input
    e.target.value = '';
}

// Open generic Question Bank search/filter (Mock for placeholder)
function openQuestionBank() {
    showToast('Question bank storage accessed. Use import/export within individual exams to copy items.', 'info');
}


// ================= LIVE MONITORING SCREEN =================
async function openLiveMonitor(examId, examTitle) {
    activeExamId = examId;
    showView('teacher-monitor');
    document.getElementById('monitor-exam-title').textContent = `Supervision: ${examTitle}`;
    
    await refreshMonitorTable();
    setupMonitorSocket(examId);
    
    // Backup poll interval just in case WebSocket gets broken/disconnected
    if (monitorInterval) clearInterval(monitorInterval);
    monitorInterval = setInterval(refreshMonitorTable, 8000);
}

// Cleanup monitor connections when switching views
const oldShowView = showView;
showView = function(viewName) {
    if (viewName !== 'teacher-monitor') {
        if (monitorSocket) {
            monitorSocket.close();
            monitorSocket = null;
        }
        if (monitorInterval) {
            clearInterval(monitorInterval);
            monitorInterval = null;
        }
    }
    oldShowView(viewName);
};

async function refreshMonitorTable() {
    if (currentView !== 'teacher-monitor') return;
    
    try {
        const attempts = await fetchApi(`/api/exams/${activeExamId}/monitor`);
        lastMonitorData = attempts;
        const tbody = document.getElementById('monitor-students-tbody');
        tbody.innerHTML = '';
        
        let activeCount = 0;
        let submittedCount = 0;
        
        if (attempts.length === 0) {
            tbody.innerHTML = `
                <tr>
                    <td colspan="7" class="text-center p-3">
                        <p class="subtitle" style="margin-bottom: 0;">No candidates have attempted this exam yet.</p>
                    </td>
                </tr>
            `;
            document.getElementById('monitor-active-count').textContent = '0';
            document.getElementById('monitor-submitted-count').textContent = '0';
            return;
        }
        
        attempts.forEach(att => {
            let statusBadge = '';
            let actionHtml = '';
            
            // Format dates
            const started = att.started_at ? new Date(att.started_at).toLocaleTimeString() : 'N/A';
            const submitted = att.submitted_at ? new Date(att.submitted_at).toLocaleTimeString() : '—';
            
            if (att.live_status === 'Active') {
                statusBadge = '<span class="badge badge-success">Active</span>';
                activeCount++;
            } else if (att.live_status === 'Disconnected') {
                statusBadge = '<span class="badge badge-warning">Disconnected</span>';
                activeCount++; // Still counted in progress
            } else if (att.status === 'violated') {
                statusBadge = '<span class="badge badge-danger">Auto Submitted (Violation)</span>';
                submittedCount++;
            } else {
                statusBadge = '<span class="badge badge-info">Submitted</span>';
                submittedCount++;
            }
            
            // Violation details
            let violationText = 'None';
            if (att.status === 'violated') {
                violationText = `<span class="text-danger" style="font-weight:600;">${att.submission_type.toUpperCase()}</span>`;
            }
            
            // Actions
            if (att.status !== 'active') {
                actionHtml = `<button class="btn btn-outline btn-xs" onclick="viewDetailedCandidateResult(${att.attempt_id})">🔍 View Answers</button>`;
            } else {
                actionHtml = `<span class="text-muted">In Progress</span>`;
            }
            
            const scoreText = att.score !== null ? `${att.score} pts` : '—';
            
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>
                    <strong>${att.student_name}</strong><br>
                    <small class="text-muted">
                        ${att.roll_no ? `Roll: ${att.roll_no} | Sec: ${att.section} | Year: ${att.year}` : (att.student_email || '—')}
                    </small>
                </td>
                <td>${statusBadge}</td>
                <td>${started}</td>
                <td>${submitted}</td>
                <td>${scoreText}</td>
                <td>${violationText}</td>
                <td>${actionHtml}</td>
            `;
            tbody.appendChild(tr);
        });
        
        document.getElementById('monitor-active-count').textContent = activeCount;
        document.getElementById('monitor-submitted-count').textContent = submittedCount;
        
    } catch (error) {
        showToast(error.message, 'danger');
    }
}

// Websocket updates for live monitoring
function setupMonitorSocket(examId) {
    if (monitorSocket) monitorSocket.close();
    
    const loc = window.location;
    const proto = loc.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${proto}//${loc.host}/ws/teacher/${examId}?token=${localStorage.getItem('token')}`;
    
    monitorSocket = new WebSocket(wsUrl);
    
    monitorSocket.onmessage = (event) => {
        const msg = JSON.parse(event.data);
        if (msg.event === 'refresh' || msg.event === 'student_status_change') {
            refreshMonitorTable();
        }
    };
    
    monitorSocket.onclose = () => {
        console.log('Monitor WebSocket closed');
    };
}

// Open candidate answers from monitor
async function viewDetailedCandidateResult(attemptId) {
    try {
        const data = await fetchApi(`/api/student/attempts/${attemptId}/result`);
        showView('student-result');
        
        // Rewrite the back action of student-result temporarily to go back to monitor
        const backBtn = document.querySelector('#view-student-result button[onclick="showView(\'student-dash\')"]');
        backBtn.onclick = () => {
            // Restore default action
            backBtn.onclick = () => showView('student-dash');
            // Go back to monitor
            openLiveMonitor(data.attempt.exam_id, data.attempt.exam_title);
        };
        
        document.getElementById('result-exam-title').textContent = `${data.student.name} - ${data.attempt.exam_title}`;
        document.getElementById('result-score').textContent = `${data.attempt.score} / ${data.attempt.exam_total_marks}`;
        document.getElementById('result-percentage').textContent = `${data.attempt.percentage}%`;
        
        const msgEl = document.getElementById('result-submission-msg');
        const iconEl = document.getElementById('result-icon');
        
        if (data.attempt.status === 'violated') {
            iconEl.textContent = '⚠️';
            msgEl.innerHTML = `<span class="text-danger" style="font-weight: 700;">Submission Violations Detected</span><br>Reason: ${data.attempt.violation_reason || 'Unknown breach'}`;
        } else {
            iconEl.textContent = '🎓';
            msgEl.textContent = 'Candidate attempt has been successfully evaluated.';
        }
        
        // Stats grid
        document.getElementById('stat-total-q').textContent = data.stats.total;
        document.getElementById('stat-correct-q').textContent = data.stats.correct;
        document.getElementById('stat-incorrect-q').textContent = data.stats.incorrect;
        document.getElementById('stat-unattempted-q').textContent = data.stats.unattempted;
        document.getElementById('stat-time-taken').textContent = data.stats.time_taken;
        document.getElementById('stat-violations').textContent = data.stats.violations_count;
        
        // Detailed questions review auto loaded
        const reviewSection = document.getElementById('detailed-answers-review');
        reviewSection.classList.remove('hidden');
        renderDetailedQuestions(data.questions);
        
    } catch (error) {
        showToast(error.message, 'danger');
    }
}

// Export candidate monitoring results to CSV
function exportMonitorCSV() {
    if (!lastMonitorData || lastMonitorData.length === 0) {
        showToast('No student attempts to export.', 'warning');
        return;
    }
    
    // Header row
    const headers = ['Name', 'Roll Number', 'Section', 'Year', 'Email', 'Live Status', 'Started Time', 'Submitted Time', 'Status', 'Score', 'Violation Reason'];
    
    const rows = lastMonitorData.map(att => [
        att.student_name,
        att.roll_no || '—',
        att.section || '—',
        att.year || '—',
        att.student_email || '—',
        att.live_status,
        att.started_at ? new Date(att.started_at).toLocaleString() : '—',
        att.submitted_at ? new Date(att.submitted_at).toLocaleString() : '—',
        att.status,
        att.score !== null ? att.score : '—',
        att.status === 'violated' ? (att.violation_reason || att.submission_type) : 'None'
    ]);
    
    // Convert rows to double-quoted escaped CSV format
    const csvString = [
        headers.join(','), 
        ...rows.map(e => e.map(val => `"${String(val).replace(/"/g, '""')}"`).join(","))
    ].join("\n");
    
    const blob = new Blob([csvString], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.setAttribute("href", url);
    link.setAttribute("download", `exam_${activeExamId}_results.csv`);
    link.style.visibility = 'hidden';
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    showToast('Results exported to CSV successfully.', 'success');
}

// Copy exam invitation/share link to clipboard for students
function copyShareLink(examId, examTitle) {
    const shareUrl = `${window.location.origin}/?exam=${examId}`;
    navigator.clipboard.writeText(shareUrl).then(() => {
        showToast(`Share link for "${examTitle}" copied to clipboard!`, 'success');
    }).catch(err => {
        // Fallback for non-secure contexts or permission blocks
        const textArea = document.createElement("textarea");
        textArea.value = shareUrl;
        textArea.style.position = "fixed";
        document.body.appendChild(textArea);
        textArea.focus();
        textArea.select();
        try {
            document.execCommand('copy');
            showToast(`Share link for "${examTitle}" copied to clipboard!`, 'success');
        } catch (e) {
            showToast('Failed to copy share link: ' + err.message, 'danger');
        }
        document.body.removeChild(textArea);
    });
}

// Convert option image file selection to base64 data URL
function handleOptionImageUpload(optionLetter) {
    const fileInput = document.getElementById(`q-opt-${optionLetter}-file`);
    const hiddenInput = document.getElementById(`q-opt-${optionLetter}-image`);
    const btn = document.getElementById(`q-opt-${optionLetter}-upload-btn`);
    
    const file = fileInput.files[0];
    if (!file) return;
    
    const reader = new FileReader();
    reader.onload = function(e) {
        hiddenInput.value = e.target.result;
        btn.innerHTML = '✅ Loaded';
        btn.classList.add('btn-success');
        showToast(`Option ${optionLetter.toUpperCase()} image uploaded!`, 'success');
    };
    reader.readAsDataURL(file);
}

// Convert question image file selection to base64 data URL
function handleQuestionImageUpload() {
    const fileInput = document.getElementById('q-image-file');
    const hiddenInput = document.getElementById('q-image');
    const btn = document.getElementById('q-image-upload-btn');
    
    const file = fileInput.files[0];
    if (!file) return;
    
    const reader = new FileReader();
    reader.onload = function(e) {
        hiddenInput.value = e.target.result;
        btn.innerHTML = '✅ Image Loaded';
        btn.classList.add('btn-success');
        showToast('Question image uploaded!', 'success');
    };
    reader.readAsDataURL(file);
}

// Reset upload button styling and status
function resetUploadButtons() {
    ['a', 'b', 'c', 'd'].forEach(let => {
        const btn = document.getElementById(`q-opt-${let}-upload-btn`);
        const hidden = document.getElementById(`q-opt-${let}-image`);
        const fileInput = document.getElementById(`q-opt-${let}-file`);
        if (fileInput) fileInput.value = '';
        if (hidden && hidden.value) {
            btn.innerHTML = '✅ Change';
            btn.classList.add('btn-success');
        } else if (btn) {
            btn.innerHTML = '🖼️ Upload';
            btn.classList.remove('btn-success');
        }
    });
    
    const qBtn = document.getElementById('q-image-upload-btn');
    const qHidden = document.getElementById('q-image');
    const qFileInput = document.getElementById('q-image-file');
    if (qFileInput) qFileInput.value = '';
    if (qHidden && qHidden.value) {
        qBtn.innerHTML = '✅ Change Image';
        qBtn.classList.add('btn-success');
    } else if (qBtn) {
        qBtn.innerHTML = '🖼️ Upload Image';
        qBtn.classList.remove('btn-success');
    }
}
