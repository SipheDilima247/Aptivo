document.addEventListener('DOMContentLoaded', () => {
  const panels = [...document.querySelectorAll('.step-panel')];
  const progressFill = document.querySelector('.progress-fill');
  const counter = document.querySelector('.wizard-counter');
  const buttons = [...document.querySelectorAll('.continue-btn, .back-btn')];
  const fileInputs = [...document.querySelectorAll('input[type="file"]')];

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

  fileInputs.forEach((input) => {
    const uploadRow = input.closest('.upload-row');
    const uploadLabel = uploadRow.querySelector('.upload-button-text');
    const defaultLabel = uploadLabel.textContent;
    const selection = uploadRow.querySelector('.file-selection');
    const filename = selection.querySelector('.file-selection-name');
    const removeButton = selection.querySelector('.file-remove');

    function updateFileSelection() {
      const file = input.files[0];
      if (!file) {
        selection.hidden = true;
        filename.textContent = '';
        uploadLabel.textContent = defaultLabel;
        return;
      }

      const size = file.size < 1024 * 1024
        ? `${Math.max(1, Math.round(file.size / 1024))} KB`
        : `${(file.size / (1024 * 1024)).toFixed(1)} MB`;
      filename.textContent = `${file.name} · ${size}`;
      selection.hidden = false;
      uploadLabel.textContent = 'Change file';
    }

    input.addEventListener('change', updateFileSelection);
    removeButton.addEventListener('click', () => {
      input.value = '';
      updateFileSelection();
    });
  });

  if (panels.length) {
    updateWizard(1);
  }
});
