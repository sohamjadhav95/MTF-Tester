/**
 * AUTH.JS — Login / Register page logic
 */
document.addEventListener('DOMContentLoaded', () => {
    // Redirect if already logged in
    if (Auth.isLoggedIn()) {
        window.location.href = '/';
        return;
    }

    // ── Tab Switching ─────────────────────────────────────────
    const tabs = document.querySelectorAll('.auth-tab');
    const loginForm = document.getElementById('login-form');
    const registerForm = document.getElementById('register-form');
    const errorDiv = document.getElementById('auth-error');

    tabs.forEach(tab => {
        tab.addEventListener('click', () => {
            tabs.forEach(t => t.classList.remove('active'));
            tab.classList.add('active');

            if (tab.dataset.tab === 'login') {
                loginForm.style.display = 'flex';
                registerForm.style.display = 'none';
            } else {
                loginForm.style.display = 'none';
                registerForm.style.display = 'flex';
            }
            errorDiv.classList.remove('visible');
        });
    });

    function showError(msg) {
        errorDiv.textContent = msg;
        errorDiv.classList.add('visible');
    }

    // ── Login ─────────────────────────────────────────────────
    loginForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const btn = document.getElementById('login-btn');
        const username = document.getElementById('login-username').value.trim();
        const password = document.getElementById('login-password').value;

        if (!username || !password) { showError('Please fill in all fields'); return; }

        setLoading(btn, true, 'Signing in...');
        errorDiv.classList.remove('visible');

        try {
            const data = await api('/api/auth/login', 'POST', { username, password });
            Auth.setToken(data.token);
            Auth.setUsername(data.username);
            window.location.href = '/';
        } catch (err) {
            showError(err.message);
        } finally {
            setLoading(btn, false, 'Sign In');
        }
    });

    // ── Register ──────────────────────────────────────────────
    registerForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const btn = document.getElementById('register-btn');
        const username = document.getElementById('reg-username').value.trim();
        const email = document.getElementById('reg-email').value.trim();
        const password = document.getElementById('reg-password').value;
        const confirm = document.getElementById('reg-confirm').value;

        if (!username || !password) { showError('Please fill in required fields'); return; }
        if (password !== confirm) { showError('Passwords do not match'); return; }
        if (password.length < 8) { showError('Password must be at least 8 characters'); return; }

        setLoading(btn, true, 'Creating account...');
        errorDiv.classList.remove('visible');

        try {
            await api('/api/auth/register', 'POST', {
                username,
                password,
                email: email || null,
            });
            // Auto-login after register
            const loginData = await api('/api/auth/login', 'POST', { username, password });
            Auth.setToken(loginData.token);
            Auth.setUsername(loginData.username);
            window.location.href = '/';
        } catch (err) {
            showError(err.message);
        } finally {
            setLoading(btn, false, 'Create Account');
        }
    });
});
