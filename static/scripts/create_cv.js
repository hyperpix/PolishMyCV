let educationCount = 1;
let experienceCount = 1;
let projectCount = 1;
let customFieldCount = 0;

function addEducation() {
  const container = document.getElementById("education-section");
  const template = `
          <div class="dynamic-item" data-section="education">
              <div class="dynamic-item-header">
                  <div class="dynamic-item-title">Education #${
                    educationCount + 1
                  }</div>
                  <button type="button" class="btn-remove" onclick="removeItem(this)">Remove</button>
              </div>
              <div class="row">
                  <div class="col-md-6">
                      <div class="form-group">
                          <label class="form-label">Degree</label>
                          <input type="text" class="form-control" name="education[${educationCount}][degree]" placeholder="Bachelor of Science in Computer Science">
                      </div>
                  </div>
                  <div class="col-md-6">
                      <div class="form-group">
                          <label class="form-label">Institution</label>
                          <input type="text" class="form-control" name="education[${educationCount}][institution]" placeholder="University of Technology">
                      </div>
                  </div>
              </div>
              <div class="row">
                  <div class="col-md-4">
                      <div class="form-group">
                          <label class="form-label">Date Range</label>
                          <input type="text" class="form-control" name="education[${educationCount}][date]" placeholder="2018 - 2022">
                      </div>
                  </div>
                  <div class="col-md-4">
                      <div class="form-group">
                          <label class="form-label">Location</label>
                          <input type="text" class="form-control" name="education[${educationCount}][location]" placeholder="Boston, MA">
                      </div>
                  </div>
                  <div class="col-md-4">
                      <div class="form-group">
                          <label class="form-label">GPA (Optional)</label>
                          <input type="text" class="form-control" name="education[${educationCount}][gpa]" placeholder="3.8/4.0">
                      </div>
                  </div>
              </div>
              <div class="form-group">
                  <label class="form-label">Additional Details</label>
                  <textarea class="form-control" name="education[${educationCount}][details]" placeholder="Relevant coursework, honors, achievements..."></textarea>
              </div>
          </div>
      `;

  container.insertAdjacentHTML("beforeend", template);
  educationCount++;
}

function addExperience() {
  const container = document.getElementById("experience-section");
  const template = `
          <div class="dynamic-item" data-section="experience">
              <div class="dynamic-item-header">
                  <div class="dynamic-item-title">Experience #${
                    experienceCount + 1
                  }</div>
                  <button type="button" class="btn-remove" onclick="removeItem(this)">Remove</button>
              </div>
              <div class="row">
                  <div class="col-md-6">
                      <div class="form-group">
                          <label class="form-label">Job Title</label>
                          <input type="text" class="form-control" name="experience[${experienceCount}][title]" placeholder="Senior Software Engineer">
                      </div>
                  </div>
                  <div class="col-md-6">
                      <div class="form-group">
                          <label class="form-label">Company</label>
                          <input type="text" class="form-control" name="experience[${experienceCount}][company]" placeholder="Tech Corp Inc.">
                      </div>
                  </div>
              </div>
              <div class="row">
                  <div class="col-md-4">
                      <div class="form-group">
                          <label class="form-label">Date Range</label>
                          <input type="text" class="form-control" name="experience[${experienceCount}][date]" placeholder="2020 - Present">
                      </div>
                  </div>
                  <div class="col-md-4">
                      <div class="form-group">
                          <label class="form-label">Location</label>
                          <input type="text" class="form-control" name="experience[${experienceCount}][location]" placeholder="San Francisco, CA">
                      </div>
                  </div>
                  <div class="col-md-4">
                      <div class="form-group">
                          <label class="form-label">Employment Type</label>
                          <input type="text" class="form-control" name="experience[${experienceCount}][type]" placeholder="Full-time">
                      </div>
                  </div>
              </div>
              <div class="form-group">
                  <label class="form-label">Job Description</label>
                  <textarea class="form-control textarea-auto" name="experience[${experienceCount}][description]" placeholder="Describe your responsibilities and achievements..."></textarea>
              </div>
          </div>
      `;

  container.insertAdjacentHTML("beforeend", template);
  experienceCount++;
}

function addCustomField() {
  const container = document.getElementById("custom-fields-container");
  const template = `
          <div class="custom-field">
              <div class="custom-field-header">
                  <div class="form-group" style="margin-bottom: 0; flex-grow: 1;">
                      <input type="text" class="form-control" name="custom[${customFieldCount}][title]" placeholder="Section Title (e.g., Certifications, Languages, Awards)">
                  </div>
                  <button type="button" class="btn-remove" onclick="removeCustomField(this)" style="margin-left: 12px;">Remove</button>
              </div>
              <div class="form-group">
                  <textarea class="form-control textarea-auto" name="custom[${customFieldCount}][content]" placeholder="Add the content for this section...&#10;&#10;For lists, separate items with new lines:&#10;• Certification 1&#10;• Certification 2&#10;• Certification 3"></textarea>
              </div>
          </div>
      `;

  container.insertAdjacentHTML("beforeend", template);
  customFieldCount++;
}

function removeItem(button) {
  const item = button.closest(".dynamic-item");
  item.remove();
}

function removeCustomField(button) {
  const field = button.closest(".custom-field");
  field.remove();
}

document.addEventListener("DOMContentLoaded", function () {
  document.getElementById("cvForm").addEventListener("submit", function (e) {
    e.preventDefault();

    const submitButton = this.querySelector(".btn-generate");
    const spinner = submitButton.querySelector(".loading-spinner");
    const icon = submitButton.querySelector("i");

    submitButton.disabled = true;
    spinner.style.display = "block";
    icon.style.display = "none";

    const formData = new FormData(this);

    fetch("/api/create-cv", {
      method: "POST",
      body: formData
    })
      .then((response) => response.json())
      .then((data) => {
        if (data.success) {
          window.location.href = data.redirect_url;
        } else {
          alert("Error: " + (data.error || "Unknown error occurred"));
          submitButton.disabled = false;
          spinner.style.display = "none";
          icon.style.display = "inline-block";
        }
      })
      .catch((error) => {
        console.error("Error:", error);
        alert(
          "An error occurred while processing your request. Please try again."
        );
        submitButton.disabled = false;
        spinner.style.display = "none";
        icon.style.display = "inline-block";
      });
  });

  const elements = document.querySelectorAll(".form-section, .submit-section");

  const observer = new IntersectionObserver(
    (entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.style.opacity = "1";
          entry.target.style.transform = "translateY(0)";
        }
      });
    },
    { threshold: 0.1 }
  );

  elements.forEach((el) => {
    observer.observe(el);
  });
});
