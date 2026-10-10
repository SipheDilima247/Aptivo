document.addEventListener('DOMContentLoaded', () => {
  const panels = [...document.querySelectorAll('.step-panel')];
  const progressFill = document.querySelector('.progress-fill');
  const counter = document.querySelector('.wizard-counter');
  const buttons = [...document.querySelectorAll('.continue-btn, .back-btn')];

  let currentStep = 1;

  function updateWizard(nextStep) {
    currentStep = nextStep;

    panels.forEach((panel) => {
      const isActive = Number(panel.dataset.step) === currentStep;
      panel.classList.toggle('active', isActive);
    });

    const progress = (currentStep / panels.length) * 100;
    if (progressFill) {
      progressFill.style.width = `${progress}%`;
    }

    if (counter) {
      counter.textContent = `${currentStep} / ${panels.length}`;
    }
  }

  buttons.forEach((button) => {
    button.addEventListener('click', () => {
      const isContinue = button.classList.contains('continue-btn');
      const nextStep = isContinue ? currentStep + 1 : currentStep - 1;

      if (isContinue && nextStep <= panels.length) {
        updateWizard(nextStep);
      }

      if (!isContinue && nextStep >= 1) {
        updateWizard(nextStep);
      }
    });
  });

  if (panels.length) {
    updateWizard(1);
  }
});
