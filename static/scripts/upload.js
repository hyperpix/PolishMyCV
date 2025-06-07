document.getElementById("uploadBtn").onclick = function () {
  document.getElementById("fileInput").click();
};
document.getElementById("fileInput").addEventListener("change", function () {
  const fileInput = this;
  const uploadBtn = document.getElementById("uploadBtn");
  if (fileInput.files && fileInput.files.length > 0) {
    uploadBtn.innerHTML =
      '<i class="fas fa-check"></i> ' + fileInput.files[0].name + " selected";
    uploadBtn.style.background = "#28ca42";
  } else {
    uploadBtn.innerHTML = '<i class="fas fa-upload"></i> Upload your resume';
    uploadBtn.style.background = "";
  }
});
document.getElementById("generateLink").onclick = async function () {
  const role = document.getElementById("jobSelect").value.trim();
  if (!role) {
    alert("Please enter a job role first.");
    return;
  }
  const jobDescArea = document.getElementById("jobDesc");
  jobDescArea.value = 'Generating job description for "' + role + '"...';
  try {
    const response = await fetch("/generate-job-desc", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ role })
    });
    const data = await response.json();
    if (data && data.description) {
      jobDescArea.value = data.description;
    } else {
      jobDescArea.value = "";
      alert("Could not generate job description.");
    }
  } catch (e) {
    jobDescArea.value = "";
    alert("Error generating job description.");
  }
};
document.getElementById("reviewBtn").onclick = async function () {
  const role = document.getElementById("jobSelect").value.trim();
  const jobDesc = document.getElementById("jobDesc").value.trim();
  const cv = {
    summary: "",
    experience: [],
    education: [],
    skills: {}
  };
  if (!jobDesc) {
    alert("Please enter or generate a job description first.");
    return;
  }
  const reviewBtn = document.getElementById("reviewBtn");
  reviewBtn.innerText = "Reviewing...";
  reviewBtn.disabled = true;
  const reviewResults = document.getElementById("reviewResults");
  reviewResults.style.display = "none";
  reviewResults.innerHTML = "";
  try {
    const response = await fetch("/api/review-cv", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        cv: cv,
        job_description: jobDesc
      })
    });
    const data = await response.json();
    if (data.error) {
      alert("Error: " + data.error);
    } else {
      document.getElementById("illustrationBlock").style.display = "none";
      let html = "";
      html += `<div class="review-section-title">CV Review Results</div>`;
      html += `<div class="review-rating-label">AI Rating</div>`;
      html += `<div class="review-rating">${data.rating ?? "--"}/100</div>`;
      html += `<div class="review-block"><div class="review-block-title">Strengths</div><ul class="review-list">${(
        data.strengths || []
      )
        .map((s) => `<li>${s}</li>`)
        .join("")}</ul></div>`;
      html += `<div class="review-block"><div class="review-block-title">Weaknesses</div><ul class="review-list">${(
        data.weaknesses || []
      )
        .map((s) => `<li>${s}</li>`)
        .join("")}</ul></div>`;
      html += `<div class="review-block"><div class="review-block-title">Suggestions</div><ul class="review-list">${(
        data.suggestions || []
      )
        .map((s) => `<li>${s}</li>`)
        .join("")}</ul></div>`;
      reviewResults.innerHTML = html;
      reviewResults.style.display = "block";
    }
  } catch (e) {
    alert("Error reviewing your resume.");
  }
  reviewBtn.innerText = "Review my resume →";
  reviewBtn.disabled = false;
};
