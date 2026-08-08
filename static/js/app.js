// Global State
let currentUser = null;
let currentView = 'auth';

// API Fetch Helper
async function fetchApi(url, options = {}) {
    options.headers = options.headers || {};
    
    // Add token from localStorage if available (as bearer token backup for cookies)
    const token = localStorage.getItem('token');
    if (token) {
        options.headers['Authorization'] = `Bearer ${token}`;
    }
    
    // Default content-type JSON
    if (options.body && typeof options.body === 'object' && !(options.body instanceof FormData)) {
        options.headers['Content-Type'] = 'application/json';
        options.body = JSON.stringify(options.body);
    }
    
    try {
        const response = await fetch(url, options);
        
        // Handle 401 Unauthorized globally
        if (response.status === 401 && currentView !== 'auth') {
            localStorage.removeItem('token');
            currentUser = null;
            updateHeader();
            showView('auth');
            showToast('Session expired. Please log in again.', 'danger');
            throw new Error('Unauthorized');
        }
        
        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.detail || 'An error occurred');
        }
        return data;
    } catch (error) {
        if (error.message !== 'Unauthorized') {
            console.error('API Error:', error);
        }
        throw error;
    }
}

// Show Specific Section (SPA Router)
function showView(viewName) {
    currentView = viewName;
    document.querySelectorAll('.view').forEach(view => {
        view.classList.add('hidden');
    });
    
    const targetView = document.getElementById(`view-${viewName}`);
    if (targetView) {
        targetView.classList.remove('hidden');
    }
    
    // Load data based on view
    if (viewName === 'student-dash') {
        loadStudentDashboard();
    } else if (viewName === 'teacher-dash') {
        loadTeacherDashboard();
    }
}

// Toast Notifications
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    if (!container) return;
    
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    
    container.appendChild(toast);
    
    setTimeout(() => {
        toast.style.opacity = '0';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// Custom Confirmation Dialog
function showConfirm(title, message, onConfirm) {
    const overlay = document.getElementById('confirm-modal');
    const titleEl = document.getElementById('confirm-title');
    const msgEl = document.getElementById('confirm-msg');
    const cancelBtn = document.getElementById('confirm-cancel-btn');
    const okBtn = document.getElementById('confirm-ok-btn');
    
    titleEl.textContent = title;
    msgEl.textContent = message;
    
    overlay.classList.remove('hidden');
    
    const cleanup = () => {
        overlay.classList.add('hidden');
        okBtn.removeEventListener('click', handleOk);
        cancelBtn.removeEventListener('click', handleCancel);
    };
    
    const handleOk = () => {
        cleanup();
        onConfirm();
    };
    
    const handleCancel = () => {
        cleanup();
    };
    
    okBtn.addEventListener('click', handleOk);
    cancelBtn.addEventListener('click', handleCancel);
}

// Auth Tab Switching
function switchAuthTab(tab) {
    const tabs = document.querySelectorAll('.auth-tab');
    const forms = document.querySelectorAll('.auth-form');
    
    tabs.forEach(t => t.classList.remove('active'));
    forms.forEach(f => f.classList.remove('active'));
    
    if (tab === 'login') {
        tabs[0].classList.add('active');
        forms[0].classList.add('active');
    } else {
        tabs[1].classList.add('active');
        forms[1].classList.add('active');
    }
}

// Header UI updates
function updateHeader() {
    const userInfo = document.getElementById('user-info');
    const nameEl = document.getElementById('user-name');
    const badgeEl = document.getElementById('user-role-badge');
    const logoutBtn = document.getElementById('logout-btn');
    
    if (currentUser) {
        userInfo.classList.remove('hidden');
        logoutBtn.classList.remove('hidden');
        nameEl.textContent = currentUser.name;
        badgeEl.textContent = currentUser.role === 'teacher' ? 'Teacher' : 'Student';
        badgeEl.className = `role-badge ${currentUser.role}`;
    } else {
        userInfo.classList.add('hidden');
        logoutBtn.classList.add('hidden');
    }
}

// Handle Form Submissions
document.getElementById('login-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const email = document.getElementById('login-email').value;
    const password = document.getElementById('login-password').value;
    
    try {
        const data = await fetchApi('/api/auth/login', {
            method: 'POST',
            body: { email, password }
        });
        
        localStorage.setItem('token', data.token);
        currentUser = data.user;
        updateHeader();
        showToast('Login successful', 'success');
        
        if (currentUser.role === 'teacher') {
            showView('teacher-dash');
        } else {
            showView('student-dash');
        }
    } catch (error) {
        showToast(error.message, 'danger');
    }
});

document.getElementById('register-form').addEventListener('submit', async (e) => {
    e.preventDefault();
    const name = document.getElementById('reg-name').value;
    const email = document.getElementById('reg-email').value;
    const password = document.getElementById('reg-password').value;
    const role = document.querySelector('input[name="reg-role"]:checked').value;
    
    try {
        const data = await fetchApi('/api/auth/register', {
            method: 'POST',
            body: { name, email, password, role }
        });
        
        localStorage.setItem('token', data.token);
        currentUser = data.user;
        updateHeader();
        showToast('Registration successful', 'success');
        
        if (currentUser.role === 'teacher') {
            showView('teacher-dash');
        } else {
            showView('student-dash');
        }
    } catch (error) {
        showToast(error.message, 'danger');
    }
});

document.getElementById('logout-btn').addEventListener('click', async () => {
    try {
        await fetchApi('/api/auth/logout', { method: 'POST' });
    } catch (e) {}
    localStorage.removeItem('token');
    currentUser = null;
    updateHeader();
    showView('auth');
    showToast('Logged out successfully', 'success');
});

// App Initialization
window.addEventListener('DOMContentLoaded', async () => {
    // Check if token exists
    const token = localStorage.getItem('token');
    if (token) {
        try {
            currentUser = await fetchApi('/api/auth/me');
            updateHeader();
            if (currentUser.role === 'teacher') {
                showView('teacher-dash');
            } else {
                showView('student-dash');
            }
        } catch (error) {
            localStorage.removeItem('token');
            showView('auth');
        }
    } else {
        showView('auth');
    }
});
