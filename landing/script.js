// DOM Elements
const copyButtons = document.querySelectorAll('.copy-btn');
const sectionLinks = document.querySelectorAll('a[href^="#"]');

// Copy to clipboard functionality
copyButtons.forEach(button => {
    button.addEventListener('click', async () => {
        const targetId = button.getAttribute('data-target');
        const codeElement = targetId ? document.getElementById(targetId) : button.closest('.code-block').querySelector('code');

        if (!codeElement) return;

        const textToCopy = codeElement.textContent.trim();

        try {
            await navigator.clipboard.writeText(textToCopy);

            // Visual feedback
            const originalText = button.textContent;
            button.textContent = 'Copied!';
            button.classList.add('copied');

            // Reset after 2 seconds
            setTimeout(() => {
                button.textContent = originalText;
                button.classList.remove('copied');
            }, 2000);

        } catch (err) {
            // Fallback for older browsers
            const textArea = document.createElement('textarea');
            textArea.value = textToCopy;
            textArea.style.position = 'fixed';
            textArea.style.left = '-999999px';
            textArea.style.top = '-999999px';
            document.body.appendChild(textArea);
            textArea.focus();
            textArea.select();

            try {
                document.execCommand('copy');
                button.textContent = 'Copied!';
                button.classList.add('copied');

                setTimeout(() => {
                    button.textContent = 'Copy';
                    button.classList.remove('copied');
                }, 2000);
            } catch (err) {
                console.error('Failed to copy text: ', err);
            }

            document.body.removeChild(textArea);
        }
    });
});

// Smooth scrolling for same-page links
sectionLinks.forEach(link => {
    link.addEventListener('click', (e) => {
        e.preventDefault();

        const targetId = link.getAttribute('href');
        const targetElement = document.querySelector(targetId);

        if (targetElement) {
            const headerOffset = 80; // Account for fixed header
            const elementPosition = targetElement.getBoundingClientRect().top;
            const offsetPosition = elementPosition + window.pageYOffset - headerOffset;

            window.scrollTo({
                top: offsetPosition,
                behavior: 'smooth'
            });
        }
    });
});

// Intersection Observer for fade-in animations
const observerOptions = {
    threshold: 0.1,
    rootMargin: '0px 0px -50px 0px'
};

const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            entry.target.style.opacity = '1';
            entry.target.style.transform = 'translateY(0)';
        }
    });
}, observerOptions);

// Observe elements for animation
document.addEventListener('DOMContentLoaded', () => {
    const animateElements = document.querySelectorAll('.feature-card, .benchmark-card, .install-step');

    animateElements.forEach(el => {
        el.style.opacity = '0';
        el.style.transform = 'translateY(20px)';
        el.style.transition = 'opacity 0.6s ease, transform 0.6s ease';
        observer.observe(el);
    });
});

// Add loading state for code copy operations
function showLoadingState(button) {
    const originalText = button.textContent;
    button.textContent = 'Copying...';
    button.disabled = true;

    return () => {
        button.textContent = originalText;
        button.disabled = false;
    };
}

// Enhanced copy functionality with loading states
copyButtons.forEach(button => {
    const originalClickHandler = button.onclick;
    button.addEventListener('click', async (e) => {
        const resetLoading = showLoadingState(button);

        // Small delay to show loading state
        await new Promise(resolve => setTimeout(resolve, 100));

        resetLoading();
    });
});

// Track analytics events (placeholder for future implementation)
function trackEvent(eventName, properties = {}) {
    // Placeholder for analytics tracking
    console.log('Event:', eventName, properties);
}

// Track copy events
copyButtons.forEach(button => {
    button.addEventListener('click', () => {
        const targetId = button.getAttribute('data-target') || 'code-block';
        trackEvent('code_copied', { target: targetId });
    });
});

// Track same-page navigation clicks
sectionLinks.forEach(link => {
    link.addEventListener('click', () => {
        const section = link.getAttribute('href');
        trackEvent('navigation_click', { section });
    });
});

console.log('BenchBox landing page loaded successfully!');
