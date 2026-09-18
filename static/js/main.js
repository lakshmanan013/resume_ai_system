// Dynamic Front-End Engine for Resume AI System (Shine / Naukri Real-Time Matching)

document.addEventListener("DOMContentLoaded", () => {
  initToastContainer();
  initAutoDismissFlash();
  initScoreBars();
  initDropzone();
  initDynamicJobFilters();
  initResumeSkillManager();
  initWhatIfSimulator();
  initAdminTableSearchAndSort();
  initAdminAjaxActions();
  initLiveJobSync();
  initQuickApply();
  init10SecondJobAutoSync();
});


// ============================================================================
// 1. Toast Notifications
// ============================================================================
function initToastContainer() {
  if (!document.getElementById("toast-container")) {
    const container = document.createElement("div");
    container.id = "toast-container";
    document.body.appendChild(container);
  }
}

function showToast(message, type = "success") {
  initToastContainer();
  const container = document.getElementById("toast-container");
  const toast = document.createElement("div");
  toast.className = `toast toast-${type}`;
  
  const icon = type === "success" ? "✓" : type === "error" ? "✕" : "ℹ";
  toast.innerHTML = `
    <span style="font-weight:700; font-size:1.1rem;">${icon}</span>
    <span>${message}</span>
    <span class="toast-close">&times;</span>
  `;
  
  toast.querySelector(".toast-close").addEventListener("click", () => {
    toast.style.opacity = "0";
    setTimeout(() => toast.remove(), 200);
  });

  container.appendChild(toast);
  
  setTimeout(() => {
    toast.style.transition = "opacity 0.4s ease, transform 0.4s ease";
    toast.style.opacity = "0";
    toast.style.transform = "translateX(50px)";
    setTimeout(() => toast.remove(), 400);
  }, 4500);
}

function initAutoDismissFlash() {
  document.querySelectorAll(".flash").forEach((el) => {
    setTimeout(() => {
      el.style.transition = "opacity 0.4s ease, max-height 0.4s ease";
      el.style.opacity = "0";
      setTimeout(() => el.remove(), 400);
    }, 4500);
  });
}

function initScoreBars() {
  document.querySelectorAll(".score-bar-fill").forEach((bar) => {
    const pct = bar.getAttribute("data-score-pct") || bar.dataset.score;
    if (pct !== undefined && pct !== null && pct !== "") {
      bar.style.width = `${pct}%`;
    }
  });
}

// ============================================================================
// 2. Dynamic Drag & Drop File Upload
// ============================================================================
function initDropzone() {
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("resume-file");
  const submitBtn = document.getElementById("upload-submit");
  const fileInfo = document.getElementById("file-info-display");
  const form = document.getElementById("upload-form");

  if (!fileInput) return;

  const updateFileInfo = (file) => {
    if (!file) return;
    const validExt = /\.(pdf|docx)$/i.test(file.name);
    const maxSize = 10 * 1024 * 1024; // 10MB

    if (!validExt) {
      showToast("Invalid file type. Please upload a PDF or DOCX file.", "error");
      if (fileInfo) fileInfo.innerHTML = `<span style="color:var(--error);">✕ Unsupported file: ${file.name}</span>`;
      if (submitBtn) submitBtn.disabled = true;
      return;
    }

    if (file.size > maxSize) {
      showToast("File is too large. Maximum size is 10MB.", "error");
      if (fileInfo) fileInfo.innerHTML = `<span style="color:var(--error);">✕ File exceeds 10MB limit</span>`;
      if (submitBtn) submitBtn.disabled = true;
      return;
    }

    const kb = (file.size / 1024).toFixed(0);
    if (fileInfo) {
      fileInfo.innerHTML = `
        <div class="dropzone-file-info">
          📄 <strong>${file.name}</strong> (${kb} KB)
        </div>
      `;
    }
    if (submitBtn) {
      submitBtn.disabled = false;
      submitBtn.classList.remove("disabled");
    }
  };

  fileInput.addEventListener("change", () => {
    if (fileInput.files.length > 0) {
      updateFileInfo(fileInput.files[0]);
    }
  });

  if (dropzone) {
    ["dragenter", "dragover"].forEach((eventName) => {
      dropzone.addEventListener(eventName, (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropzone.classList.add("drag-over");
      });
    });

    ["dragleave", "drop"].forEach((eventName) => {
      dropzone.addEventListener(eventName, (e) => {
        e.preventDefault();
        e.stopPropagation();
        dropzone.classList.remove("drag-over");
      });
    });

    dropzone.addEventListener("drop", (e) => {
      if (e.dataTransfer.files.length > 0) {
        fileInput.files = e.dataTransfer.files;
        updateFileInfo(e.dataTransfer.files[0]);
      }
    });

    dropzone.addEventListener("click", () => {
      fileInput.click();
    });
  }

  if (form && submitBtn) {
    form.addEventListener("submit", () => {
      submitBtn.disabled = true;
      submitBtn.innerHTML = `
        <span style="display:inline-block; animation:pulse 1s infinite;">⚙ Parsing resume with AI...</span>
      `;
    });
  }
}

// ============================================================================
// 3. Dynamic Job Filtering, Live Search & Work Mode Filters (Zero-Reload)
// ============================================================================
function initDynamicJobFilters() {
  const container = document.getElementById("job-list-container");
  if (!container) return;

  const slider = document.getElementById("threshold-slider");
  const thresholdVal = document.getElementById("threshold-value");
  const locationSelect = document.getElementById("location-filter");
  const modeSelect = document.getElementById("work-mode-filter");
  const senioritySelect = document.getElementById("seniority-filter");
  const searchInput = document.getElementById("job-search-input");
  const sortSelect = document.getElementById("job-sort-select");
  const countBadge = document.getElementById("matching-jobs-count");
  const emptyState = document.getElementById("jobs-empty-state");

  const filterJobs = () => {
    const minThreshold = slider ? parseInt(slider.value, 10) : 0;
    const selectedLocation = locationSelect ? locationSelect.value.toLowerCase().trim() : "";
    const selectedMode = modeSelect ? modeSelect.value.toLowerCase().trim() : "";
    const selectedSeniority = senioritySelect ? senioritySelect.value.toLowerCase().trim() : "";
    const query = searchInput ? searchInput.value.toLowerCase().trim() : "";
    const sortBy = sortSelect ? sortSelect.value : "score_desc";

    const jobCards = Array.from(container.querySelectorAll(".job-card-item"));
    let visibleCount = 0;

    jobCards.forEach((card) => {
      const score = parseFloat(card.dataset.score || 0);
      const location = (card.dataset.location || "").toLowerCase();
      const mode = (card.dataset.mode || "").toLowerCase();
      const seniority = (card.dataset.seniority || "").toLowerCase();
      const title = (card.dataset.title || "").toLowerCase();
      const company = (card.dataset.company || "").toLowerCase();
      const skills = (card.dataset.skills || "").toLowerCase();

      const matchesThreshold = score >= minThreshold;
      const matchesLocation = !selectedLocation || location.includes(selectedLocation) || (selectedLocation === "remote" && location.includes("remote"));
      const matchesMode = !selectedMode || mode.includes(selectedMode);
      const matchesSeniority = !selectedSeniority || seniority.includes(selectedSeniority);
      const matchesSearch = !query || title.includes(query) || company.includes(query) || skills.includes(query) || location.includes(query);

      if (matchesThreshold && matchesLocation && matchesMode && matchesSeniority && matchesSearch) {
        card.style.display = "flex";
        visibleCount++;
      } else {
        card.style.display = "none";
      }
    });

    // Sort visible cards
    jobCards.sort((a, b) => {
      const scoreA = parseFloat(a.dataset.score || 0);
      const scoreB = parseFloat(b.dataset.score || 0);
      const expA = parseFloat(a.dataset.experience || 0);
      const expB = parseFloat(b.dataset.experience || 0);
      const titleA = (a.dataset.title || "").toLowerCase();
      const titleB = (b.dataset.title || "").toLowerCase();

      if (sortBy === "score_desc") return scoreB - scoreA;
      if (sortBy === "score_asc") return scoreA - scoreB;
      if (sortBy === "exp_asc") return expA - expB;
      if (sortBy === "exp_desc") return expB - expA;
      if (sortBy === "title_asc") return titleA.localeCompare(titleB);
      return 0;
    });

    jobCards.forEach((card) => container.appendChild(card));

    if (countBadge) {
      countBadge.textContent = `${visibleCount} role${visibleCount === 1 ? '' : 's'}`;
    }

    if (emptyState) {
      emptyState.style.display = visibleCount === 0 ? "block" : "none";
    }
  };

  if (slider) {
    slider.addEventListener("input", () => {
      if (thresholdVal) thresholdVal.textContent = slider.value + "%";
      filterJobs();
    });
  }

  if (locationSelect) locationSelect.addEventListener("change", filterJobs);
  if (modeSelect) modeSelect.addEventListener("change", filterJobs);
  if (senioritySelect) senioritySelect.addEventListener("change", filterJobs);
  if (searchInput) searchInput.addEventListener("input", filterJobs);
  if (sortSelect) sortSelect.addEventListener("change", filterJobs);

  // Initial pass & score bars
  filterJobs();
  initScoreBars();
}

// ============================================================================
// 4. Dynamic Resume Skill Manager & Profile Customizer (AJAX)
// ============================================================================
function initResumeSkillManager() {
  const skillManager = document.getElementById("resume-skill-manager");
  if (!skillManager) return;

  const resumeId = skillManager.dataset.resumeId;
  const skillsContainer = document.getElementById("editable-skills-list");
  const addSkillInput = document.getElementById("add-skill-input");
  const addSkillBtn = document.getElementById("add-skill-btn");
  const autocompleteList = document.getElementById("skill-autocomplete-list");
  const expInput = document.getElementById("edit-experience-years");
  const nameInput = document.getElementById("edit-parsed-name");
  const saveDetailsBtn = document.getElementById("save-details-btn");

  let currentSkills = JSON.parse(skillManager.dataset.skills || "[]");

  const renderSkills = () => {
    if (!skillsContainer) return;
    skillsContainer.innerHTML = "";
    if (currentSkills.length === 0) {
      skillsContainer.innerHTML = '<span class="text-muted">No skills listed yet. Add some below!</span>';
      return;
    }

    currentSkills.forEach((skill) => {
      const tag = document.createElement("span");
      tag.className = "skill-tag-editable";
      tag.innerHTML = `
        <span>${skill}</span>
        <span class="skill-tag-remove" data-skill="${skill}" title="Remove skill">&times;</span>
      `;
      tag.querySelector(".skill-tag-remove").addEventListener("click", () => {
        removeSkill(skill);
      });
      skillsContainer.appendChild(tag);
    });

    const countElem = document.getElementById("skills-count-badge");
    if (countElem) countElem.textContent = currentSkills.length;
  };

  const syncResumeUpdates = async (overrideData = {}) => {
    try {
      const payload = {
        skills: currentSkills,
        experience_years: expInput ? expInput.value : undefined,
        parsed_name: nameInput ? nameInput.value : undefined,
        ...overrideData
      };

      const res = await fetch(`/api/resume/${resumeId}/update`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });

      const data = await res.json();
      if (data.success) {
        showToast(data.message || "Resume updated & job matches recalculated!", "success");
        skillManager.dataset.skills = JSON.stringify(data.resume.skills);
        currentSkills = data.resume.skills;
        renderSkills();
        updateDynamicMatchesPreview(data.ranked_jobs);
      } else {
        showToast(data.error || "Failed to update resume", "error");
      }
    } catch (err) {
      showToast("Network error updating resume", "error");
    }
  };

  const addSkill = (skillName) => {
    const clean = skillName.trim().toLowerCase();
    if (!clean) return;
    if (currentSkills.includes(clean)) {
      showToast(`'${clean}' is already in your skills!`, "info");
      return;
    }
    currentSkills.push(clean);
    currentSkills.sort();
    if (addSkillInput) addSkillInput.value = "";
    if (autocompleteList) autocompleteList.style.display = "none";
    renderSkills();
    syncResumeUpdates();
  };

  const removeSkill = (skillName) => {
    currentSkills = currentSkills.filter((s) => s !== skillName);
    renderSkills();
    syncResumeUpdates();
  };

  if (addSkillBtn && addSkillInput) {
    addSkillBtn.addEventListener("click", () => addSkill(addSkillInput.value));
    addSkillInput.addEventListener("keydown", (e) => {
      if (e.key === "Enter") {
        e.preventDefault();
        addSkill(addSkillInput.value);
      }
    });
  }

  // Autocomplete
  if (addSkillInput && autocompleteList) {
    let debounceTimer;
    addSkillInput.addEventListener("input", () => {
      clearTimeout(debounceTimer);
      const query = addSkillInput.value.trim().toLowerCase();
      if (!query) {
        autocompleteList.style.display = "none";
        return;
      }
      debounceTimer = setTimeout(async () => {
        try {
          const res = await fetch(`/api/skills/suggestions?q=${encodeURIComponent(query)}`);
          const data = await res.json();
          if (data.skills && data.skills.length > 0) {
            autocompleteList.innerHTML = "";
            data.skills.forEach((s) => {
              const item = document.createElement("div");
              item.className = "autocomplete-item";
              item.textContent = s;
              item.addEventListener("click", () => {
                addSkill(s);
              });
              autocompleteList.appendChild(item);
            });
            autocompleteList.style.display = "block";
          } else {
            autocompleteList.style.display = "none";
          }
        } catch (e) {
          autocompleteList.style.display = "none";
        }
      }, 200);
    });

    document.addEventListener("click", (e) => {
      if (!skillManager.contains(e.target)) {
        autocompleteList.style.display = "none";
      }
    });
  }

  if (saveDetailsBtn) {
    saveDetailsBtn.addEventListener("click", () => syncResumeUpdates());
  }

  renderSkills();
}

function updateDynamicMatchesPreview(rankedJobs) {
  const previewContainer = document.getElementById("live-matches-preview");
  if (!previewContainer || !rankedJobs) return;

  if (rankedJobs.length === 0) {
    previewContainer.innerHTML = '<p class="text-muted">No jobs match your updated profile.</p>';
    return;
  }

  const topJobs = rankedJobs.slice(0, 4);
  let html = '<div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(220px, 1fr)); gap:16px; margin-top:12px;">';
  topJobs.forEach((job) => {
    const scoreColor = job.score >= 70 ? 'var(--success)' : job.score >= 40 ? 'var(--primary)' : 'var(--warning)';
    html += `
      <div class="card mb-0" style="padding:16px; border-left:4px solid ${scoreColor};">
        <h4 style="font-size:1rem; margin-bottom:4px;"><a href="/jobs/${job.id}">${job.title}</a></h4>
        <div class="text-muted" style="font-size:0.82rem; margin-bottom:8px;">${job.company} &middot; ${job.location} &middot; ${job.job_type || 'Full-Time'}</div>
        <div style="display:flex; justify-content:space-between; align-items:center;">
          <span style="font-weight:700; font-size:1.1rem; color:${scoreColor};">${job.score}% match</span>
          <a href="/jobs/${job.id}" class="btn btn-secondary btn-sm" style="padding:4px 10px; font-size:0.75rem;">View Fit</a>
        </div>
      </div>
    `;
  });
  html += '</div>';
  previewContainer.innerHTML = html;
}

// ============================================================================
// 5. Dynamic What-If Skill Impact Simulator
// ============================================================================
function initWhatIfSimulator() {
  document.querySelectorAll(".simulate-skill-btn").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.preventDefault();
      const resumeId = btn.dataset.resumeId;
      const jobId = btn.dataset.jobId;
      const skillName = btn.dataset.skill;

      if (!resumeId || !skillName) return;

      try {
        btn.disabled = true;
        btn.textContent = "Calculating fit...";

        const res = await fetch(`/api/resume/${resumeId}/simulate-skill`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            extra_skills: [skillName],
            job_id: jobId ? parseInt(jobId, 10) : undefined
          })
        });

        const data = await res.json();
        if (data.success && data.job_id) {
          const newScore = data.simulated_match.score;
          const diff = data.diff;
          
          showToast(`Adding '${skillName}' boosts your match score from ${data.original_match.score}% to ${newScore}% (+${diff}%)!`, "success");

          const scoreNumElem = document.getElementById("job-match-score-display");
          const scoreFillElem = document.getElementById("job-match-bar-fill");
          if (scoreNumElem) {
            scoreNumElem.textContent = `${newScore}%`;
            scoreNumElem.style.color = "var(--success)";
          }
          if (scoreFillElem) {
            scoreFillElem.style.width = `${newScore}%`;
          }

          btn.textContent = `+${diff}% Boosted!`;
          btn.classList.remove("btn-secondary");
          btn.classList.add("btn-accent");
        }
      } catch (err) {
        showToast("Error simulating skill", "error");
        btn.disabled = false;
        btn.textContent = `+ Test "${skillName}"`;
      }
    });
  });
}

// ============================================================================
// 6. Admin Table Live Search & Sortable Columns
// ============================================================================
function initAdminTableSearchAndSort() {
  document.querySelectorAll(".admin-searchable-table").forEach((table) => {
    const tableId = table.id;
    const searchInput = document.querySelector(`[data-table-target="${tableId}"]`);
    const roleFilter = document.querySelector(`[data-table-role="${tableId}"]`);
    const statusFilter = document.querySelector(`[data-table-status="${tableId}"]`);
    const modeFilter = document.querySelector(`[data-table-mode="${tableId}"]`);
    const rows = Array.from(table.querySelectorAll("tbody tr"));

    const filterTable = () => {
      const q = searchInput ? searchInput.value.toLowerCase().trim() : "";
      const role = roleFilter ? roleFilter.value.toLowerCase().trim() : "";
      const status = statusFilter ? statusFilter.value.toLowerCase().trim() : "";
      const mode = modeFilter ? modeFilter.value.toLowerCase().trim() : "";

      rows.forEach((row) => {
        const text = row.textContent.toLowerCase();
        const rowRole = (row.dataset.role || "").toLowerCase();
        const rowStatus = (row.dataset.status || "").toLowerCase();
        const rowMode = (row.dataset.mode || "").toLowerCase();

        const matchQ = !q || text.includes(q);
        const matchRole = !role || rowRole === role;
        const matchStatus = !status || rowStatus === status;
        const matchMode = !mode || rowMode.includes(mode);

        if (matchQ && matchRole && matchStatus && matchMode) {
          row.style.display = "";
        } else {
          row.style.display = "none";
        }
      });
    };

    if (searchInput) searchInput.addEventListener("input", filterTable);
    if (roleFilter) roleFilter.addEventListener("change", filterTable);
    if (statusFilter) statusFilter.addEventListener("change", filterTable);
    if (modeFilter) modeFilter.addEventListener("change", filterTable);

    // Click to Sort Table
    table.querySelectorAll("th[data-sort]").forEach((th) => {
      th.style.cursor = "pointer";
      th.innerHTML += ' <span class="sort-icon">⇅</span>';
      
      let asc = true;
      th.addEventListener("click", () => {
        const colIndex = Array.from(th.parentNode.children).indexOf(th);
        const isNumeric = th.dataset.sort === "num";

        rows.sort((a, b) => {
          const valA = a.children[colIndex].textContent.trim();
          const valB = b.children[colIndex].textContent.trim();
          if (isNumeric) {
            return asc ? parseFloat(valA || 0) - parseFloat(valB || 0) : parseFloat(valB || 0) - parseFloat(valA || 0);
          }
          return asc ? valA.localeCompare(valB) : valB.localeCompare(valA);
        });

        asc = !asc;
        th.querySelector(".sort-icon").textContent = asc ? "▲" : "▼";
        const tbody = table.querySelector("tbody") || table;
        rows.forEach((r) => tbody.appendChild(r));
      });
    });
  });
}

// ============================================================================
// 7. Dynamic Admin AJAX In-Place Actions
// ============================================================================
function initAdminAjaxActions() {
  // Toggle User Active / Inactive
  document.querySelectorAll(".ajax-toggle-user").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.preventDefault();
      const userId = btn.dataset.userId;
      const row = document.getElementById(`user-row-${userId}`);
      if (!userId) return;

      try {
        btn.disabled = true;
        const res = await fetch(`/api/admin/users/${userId}/toggle`, { method: "POST" });
        const data = await res.json();

        if (data.success) {
          showToast(data.message, "success");
          btn.textContent = data.is_active ? "Deactivate" : "Reactivate";
          btn.className = `btn btn-sm ${data.is_active ? 'btn-danger' : 'btn-secondary'} ajax-toggle-user`;
          
          if (row) {
            row.dataset.status = data.is_active ? "active" : "inactive";
            const badge = row.querySelector(".user-status-badge");
            if (badge) {
              badge.className = `badge ${data.is_active ? 'badge-active' : 'badge-inactive'} user-status-badge`;
              badge.textContent = data.is_active ? "active" : "inactive";
            }
          }
        } else {
          showToast(data.error || "Action failed", "error");
        }
      } catch (err) {
        showToast("Error updating user status", "error");
      } finally {
        btn.disabled = false;
      }
    });
  });

  // Toggle Job Active / Hidden
  document.querySelectorAll(".ajax-toggle-job").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.preventDefault();
      const jobId = btn.dataset.jobId;
      const row = document.getElementById(`job-row-${jobId}`);
      if (!jobId) return;

      try {
        btn.disabled = true;
        const res = await fetch(`/api/admin/jobs/${jobId}/toggle`, { method: "POST" });
        const data = await res.json();

        if (data.success) {
          showToast(data.message, "success");
          btn.textContent = data.is_active ? "Hide" : "Show";
          
          if (row) {
            row.dataset.status = data.is_active ? "active" : "hidden";
            const badge = row.querySelector(".job-status-badge");
            if (badge) {
              badge.className = `badge ${data.is_active ? 'badge-active' : 'badge-inactive'} job-status-badge`;
              badge.textContent = data.is_active ? "active" : "hidden";
            }
          }
        } else {
          showToast(data.error || "Action failed", "error");
        }
      } catch (err) {
        showToast("Error updating job visibility", "error");
      } finally {
        btn.disabled = false;
      }
    });
  });

  // Delete Job with in-place fade out
  document.querySelectorAll(".ajax-delete-job").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.preventDefault();
      const jobId = btn.dataset.jobId;
      const jobTitle = btn.dataset.jobTitle || "this job listing";
      const row = document.getElementById(`job-row-${jobId}`);

      if (!confirm(`Are you sure you want to delete "${jobTitle}"? This cannot be undone.`)) {
        return;
      }

      try {
        btn.disabled = true;
        const res = await fetch(`/api/admin/jobs/${jobId}/delete`, { method: "POST" });
        const data = await res.json();

        if (data.success) {
          showToast(data.message, "success");
          if (row) {
            row.style.transition = "all 0.3s ease";
            row.style.opacity = "0";
            row.style.transform = "scaleY(0)";
            setTimeout(() => row.remove(), 300);
          }
        } else {
          showToast(data.error || "Delete failed", "error");
          btn.disabled = false;
        }
      } catch (err) {
        showToast("Error deleting job", "error");
        btn.disabled = false;
      }
    });
  });
}

// ============================================================================
// 8. Live Real-Time Job Sync & 1-Click Apply
// ============================================================================
function initLiveJobSync() {
  const syncBtn = document.getElementById("admin-sync-jobs-btn");
  if (!syncBtn) return;

  syncBtn.addEventListener("click", async () => {
    try {
      syncBtn.disabled = true;
      syncBtn.innerHTML = "⏳ Syncing Adzuna Live Jobs...";
      
      const res = await fetch("/api/admin/jobs/sync", { method: "POST" });
      const data = await res.json();
      
      if (data.success) {
        showToast(data.message, "success");
        setTimeout(() => window.location.reload(), 800);
      } else {
        showToast(data.error || "Sync failed", "error");
        syncBtn.disabled = false;
        syncBtn.innerHTML = "⚡ Sync Adzuna Jobs";
      }
    } catch (err) {
      showToast("Network error syncing jobs", "error");
      syncBtn.disabled = false;
      syncBtn.innerHTML = "⚡ Sync Adzuna Jobs";
    }
  });
}

function initQuickApply() {
  document.querySelectorAll(".quick-apply-btn").forEach((btn) => {
    btn.addEventListener("click", async (e) => {
      e.preventDefault();
      const jobId = btn.dataset.jobId;
      const jobTitle = btn.dataset.jobTitle || "this position";
      const company = btn.dataset.company || "the hiring team";

      if (!jobId) return;

      try {
        btn.disabled = true;
        btn.innerHTML = "Submitting...";

        const res = await fetch(`/api/jobs/${jobId}/apply`, { method: "POST" });
        const data = await res.json();

        if (data.success) {
          showToast(data.message, "success");
          btn.innerHTML = "✓ Applied!";
          btn.classList.remove("btn-primary");
          btn.classList.add("btn-accent");
        } else {
          showToast(data.error || "Application error", "error");
          btn.disabled = false;
          btn.innerHTML = "⚡ Quick Apply";
        }
      } catch (err) {
        showToast("Error sending application", "error");
        btn.disabled = false;
        btn.innerHTML = "⚡ Quick Apply";
      }
    });
  });
}

// ============================================================================
// 9. Real-Time 10-Second Adzuna Auto-Sync & Dynamic Feed Ingestion
// ============================================================================
function init10SecondJobAutoSync() {
  const syncBanner = document.getElementById("live-sync-banner");
  const adminLastSyncText = document.getElementById("admin-last-synced-text");
  const jobListContainer = document.getElementById("job-list-container");
  const manualSyncBtn = document.getElementById("manual-sync-trigger-btn");
  const clockLabel = document.getElementById("live-sync-clock");
  const countBadge = document.getElementById("matching-jobs-count");

  // Only run if user is on a page displaying live jobs
  if (!syncBanner && !adminLastSyncText && !jobListContainer) {
    return;
  }

  // Set of job IDs currently rendered on page
  const knownJobIds = new Set();
  if (jobListContainer) {
    jobListContainer.querySelectorAll(".job-card-item").forEach((card) => {
      const applyBtn = card.querySelector(".quick-apply-btn");
      if (applyBtn && applyBtn.dataset.jobId) {
        knownJobIds.add(String(applyBtn.dataset.jobId));
      }
    });
  }

  async function checkLiveUpdates(isManual = false) {
    try {
      if (clockLabel && isManual) {
        clockLabel.textContent = "Syncing live with Adzuna...";
      }

      const url = isManual ? "/api/jobs/sync-now" : "/api/jobs/live-feed";
      const method = isManual ? "POST" : "GET";
      const res = await fetch(url, { method });
      const data = await res.json();

      if (!data.success) return;

      const now = new Date();
      const timeStr = now.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });

      if (clockLabel) {
        clockLabel.textContent = `Auto-synced: ${timeStr} · Active: ${data.total_active_jobs || ''} jobs`;
      }
      if (adminLastSyncText) {
        adminLastSyncText.textContent = `Auto-sync: 10s (Active: ${data.total_active_jobs || ''} · ${timeStr})`;
      }

      // Detect incoming jobs from latest active feed
      const incomingJobs = data.latest_jobs || [];
      const brandNewJobs = incomingJobs.filter((j) => j && j.id && !knownJobIds.has(String(j.id)));

      if (brandNewJobs.length > 0) {
        showToast(`⚡ ${brandNewJobs.length} new live jobs synced from Adzuna!`, "success");

        if (jobListContainer) {
          brandNewJobs.forEach((job) => {
            knownJobIds.add(String(job.id));
            const cardHtml = createLiveJobCardHtml(job);
            jobListContainer.insertAdjacentHTML("afterbegin", cardHtml);
          });

          // Update total roles badge
          if (countBadge) {
            const currentTotal = jobListContainer.querySelectorAll(".job-card-item").length;
            countBadge.textContent = `${currentTotal} roles`;
          }

          // Re-bind click events for newly inserted quick apply buttons
          initQuickApply();
        }

        // If on admin jobs table, dynamically insert row
        const adminTable = document.getElementById("jobs-table");
        if (adminTable) {
          const tbody = adminTable.querySelector("tbody");
          if (tbody) {
            brandNewJobs.forEach((job) => {
              const rowHtml = createAdminJobRowHtml(job);
              tbody.insertAdjacentHTML("afterbegin", rowHtml);
            });
            initAdminAjaxActions();
          }
        }
      } else if (isManual) {
        showToast("Adzuna sync check complete! Database is up to date.", "info");
      }
    } catch (err) {
      console.warn("Live job auto-sync tick notice:", err);
    }
  }

  // Bind manual sync button if present
  if (manualSyncBtn) {
    manualSyncBtn.addEventListener("click", () => {
      manualSyncBtn.disabled = true;
      manualSyncBtn.innerHTML = "⏳ Syncing...";
      checkLiveUpdates(true).finally(() => {
        manualSyncBtn.disabled = false;
        manualSyncBtn.innerHTML = "⚡ Sync Now";
      });
    });
  }

  // Auto-sync poll every 10 seconds!
  setInterval(() => {
    checkLiveUpdates(false);
  }, 10000);
}

function createLiveJobCardHtml(job) {
  const reqSkills = job.required_skills || [];
  const skillsBadges = reqSkills.slice(0, 5).map((s) => `<span class="badge badge-skill">${s}</span>`).join(" ");
  const salaryText = job.salary_min ? `₹${Number(job.salary_min).toLocaleString()}` : "Competitive";

  return `
  <div class="job-card job-card-item is-new-live-job"
       data-score="85"
       data-location="${job.location || 'Remote'}"
       data-title="${job.title || ''}"
       data-company="${job.company || ''}"
       data-mode="${(job.job_type || 'Full-Time').toLowerCase()}"
       data-seniority="${(job.seniority_level || 'Mid-Level').toLowerCase()}"
       data-skills="${reqSkills.join(' ')}"
       data-experience="${job.min_experience || 0}">
    <div class="job-info">
      <div class="flex-between" style="justify-content: flex-start; gap: 10px; margin-bottom: 4px; flex-wrap: wrap;">
        <h3 class="job-title" style="margin: 0;">
          <a href="/jobs/${job.id}" style="color: inherit; text-decoration: none;">${job.title}</a>
        </h3>
        <span class="badge-live-new">⚡ NEW LIVE</span>
        <span class="badge" style="background:#dbeafe; color:#1d4ed8; font-weight:700;">Adzuna</span>
      </div>
      <div class="job-company" style="font-weight: 600; color: var(--text-body); margin-bottom: 8px;">
        ${job.company} &middot; <span class="text-muted">${job.location || 'Remote'}</span>
      </div>
      <div class="job-meta-row" style="display: flex; gap: 16px; font-size: 0.82rem; color: var(--text-muted); margin-bottom: 12px; flex-wrap: wrap;">
        <span>💼 ${job.job_type || 'Full-Time'}</span>
        <span>📈 ${job.seniority_level || 'Mid-Level'}</span>
        <span>⏳ ${job.min_experience || 0}+ yrs exp</span>
        <span>💰 ${salaryText}</span>
      </div>
      <div class="skill-chips-row" style="display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 14px;">
        ${skillsBadges}
      </div>
    </div>
    <div class="job-actions" style="display: flex; flex-direction: column; align-items: flex-end; justify-content: space-between; gap: 12px;">
      <div class="score-pill score-high" style="font-weight: 800; font-size: 1.05rem; padding: 6px 14px; border-radius: var(--radius-full); background: #ecfdf5; color: #059669; border: 1px solid #a7f3d0;">
        ⚡ Live Opening
      </div>
      <div style="display: flex; gap: 8px;">
        <a href="/jobs/${job.id}" class="btn btn-secondary btn-sm">View Details</a>
        <button type="button" class="btn btn-primary btn-sm quick-apply-btn"
                data-job-id="${job.id}"
                data-job-title="${job.title}"
                data-company="${job.company}">
          ⚡ Quick Apply
        </button>
      </div>
    </div>
  </div>
  `;
}

function createAdminJobRowHtml(job) {
  const reqSkills = (job.required_skills || []).slice(0, 3).map((s) => `<span class="badge badge-skill">${s}</span>`).join(" ");
  const viewLink = job.source_url ? `<a href="${job.source_url}" target="_blank" rel="noopener noreferrer" class="btn btn-secondary btn-sm" style="padding:4px 8px; font-size:0.78rem;">↗ View</a>` : "";

  return `
  <tr style="background: rgba(16, 185, 129, 0.06); animation: live-card-slide-in 0.5s ease;">
    <td>
      <div style="font-weight:600; color:var(--text-main);">${job.title} <span class="badge-live-new" style="font-size:0.68rem; padding:2px 6px;">NEW</span></div>
      <div style="font-size:0.8rem; color:var(--text-muted);">${job.company} &middot; ${job.location || 'Remote'}</div>
    </td>
    <td><span class="badge badge-active">Active</span></td>
    <td><span class="badge" style="background:#dbeafe; color:#1d4ed8; font-weight:700;">Adzuna</span></td>
    <td><span class="badge badge-skill">${job.seniority_level || 'Mid-Level'}</span></td>
    <td>${job.min_experience || 0} yrs</td>
    <td>${reqSkills}</td>
    <td><span class="badge" style="background:#ecfdf5; color:#059669; font-weight:700;">Just now</span></td>
    <td style="white-space:nowrap; text-align:right;">
      <div class="table-actions">
        <span class="badge" style="background:#f3f4f6; color:#6b7280; font-size:0.78rem; padding:4px 8px; border:1px solid #e5e7eb;">Read-Only</span>
        ${viewLink}
        <button type="button" class="btn btn-secondary btn-sm ajax-toggle-job" data-job-id="${job.id}">Hide</button>
        <button type="button" class="btn btn-danger btn-sm ajax-delete-job" data-job-id="${job.id}" data-job-title="${job.title}">Delete</button>
      </div>
    </td>
  </tr>
  `;
}

