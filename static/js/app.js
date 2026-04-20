// Cloud Todo App - Client JS
document.addEventListener('DOMContentLoaded', () => {
    // Show selected filename next to the file input
    const fileInput = document.querySelector('.file-input');
    const fileBtn = document.querySelector('.file-btn');
    if (fileInput && fileBtn) {
        fileInput.addEventListener('change', () => {
            if (fileInput.files.length > 0) {
                fileBtn.textContent = '📎 ' + fileInput.files[0].name;
            } else {
                fileBtn.textContent = '📎 Attach file';
            }
        });
    }

    // Auto-dismiss flash messages after 4 seconds
    document.querySelectorAll('.flash').forEach(el => {
        setTimeout(() => {
            el.style.transition = 'opacity 0.5s';
            el.style.opacity = '0';
            setTimeout(() => el.remove(), 500);
        }, 4000);
    });
});
