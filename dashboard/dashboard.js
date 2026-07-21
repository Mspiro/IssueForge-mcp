/**
 * IssueForge dashboard — pure client-side rendering, sort, and filter.
 *
 * Two data-loading modes:
 * - Static build (dashboard.py build/record): data is embedded inline as
 *   window.DASHBOARD_DATA at build time, since a file:// page generally
 *   can't fetch() a sibling JSON file (browsers block file: scheme CORS).
 * - Served (dashboard_server.py): window.DASHBOARD_DATA is absent, so this
 *   fetches /api/data instead — same-origin over http://, no CORS issue.
 *   This is also what makes the Refresh button and lifetime stats work,
 *   since those need a real server to call.
 */
(function () {
  "use strict";

  const data = window.DASHBOARD_DATA || { issues: [], generated_at: null };
  const servedMode = !window.DASHBOARD_DATA;
  let sortKey = "last_worked";
  let sortDir = -1;
  let activeFilter = "all";
  let searchTerm = "";

  const STATUS_PILL = {
    "fixed": "green", "closed (fixed)": "green", "closed (duplicate)": "gray",
    "closed (won't fix)": "gray", "closed (works as designed)": "gray",
    "needs review": "amber", "reviewed & tested by the community": "amber",
    "needs work": "amber", "active": "amber", "postponed": "gray",
  };

  function pillClass(statusValue) {
    if (!statusValue) return "gray";
    return STATUS_PILL[statusValue.toLowerCase()] || "gray";
  }

  function pipelinePillClass(status, label) {
    // detailed_label ("passed with warnings") is a more specific read on
    // GitLab's own coarse top-level "success" status (which still reports
    // "success" even when a job failed with allow_failure — see
    // gitlab_mr_client.get_latest_pipeline_status) — check it first.
    if (label && /warning/i.test(label)) return "amber";
    if (status === "success") return "green";
    if (status === "failed") return "red";
    if (status === "running" || status === "pending") return "amber";
    return "gray";
  }

  function escapeHtml(s) {
    const div = document.createElement("div");
    div.textContent = s == null ? "" : String(s);
    return div.innerHTML;
  }

  function matchesFilter(issue) {
    if (activeFilter === "all") return true;
    if (activeFilter === "new-activity") {
      return (issue.comments && issue.comments.new_since_last_check > 0);
    }
    if (activeFilter === "red-pipeline") {
      return issue.mr && issue.mr.pipeline_status === "failed";
    }
    if (activeFilter === "credited") {
      return issue.credit && issue.credit.credited;
    }
    if (activeFilter === "open-mr") {
      return issue.mr && issue.mr.iid && issue.mr.state === "opened";
    }
    if (activeFilter === "issueforge") {
      return (issue.source || "issueforge") === "issueforge";
    }
    if (activeFilter === "imported") {
      return issue.source === "imported";
    }
    return true;
  }

  function matchesSearch(issue) {
    if (!searchTerm) return true;
    const haystack = [
      issue.issue_id, issue.title, issue.project, issue.action_summary,
      ...(issue.action_steps || []),
    ].join(" ").toLowerCase();
    return haystack.includes(searchTerm);
  }

  function compareIssues(a, b) {
    const av = getSortValue(a);
    const bv = getSortValue(b);
    if (av < bv) return -1 * sortDir;
    if (av > bv) return 1 * sortDir;
    return 0;
  }

  function getSortValue(issue) {
    switch (sortKey) {
      case "issue_id": return Number(issue.issue_id) || 0;
      case "title": return (issue.title || "").toLowerCase();
      case "last_worked": return issue.last_worked || "";
      case "status": return (issue.status && issue.status.value) || "";
      case "mr": return (issue.mr && issue.mr.pipeline_status) || "";
      case "credit": return (issue.credit && issue.credit.credited) ? 1 : 0;
      case "source": return issue.source || "issueforge";
      default: return "";
    }
  }

  function renderStats(issues) {
    const total = issues.length;
    const newActivity = issues.filter(i => i.comments && i.comments.new_since_last_check > 0).length;
    const redPipelines = issues.filter(i => i.mr && i.mr.pipeline_status === "failed").length;
    const credited = issues.filter(i => i.credit && i.credit.credited).length;
    document.getElementById("stat-total").textContent = total;
    document.getElementById("stat-new").textContent = newActivity;
    document.getElementById("stat-red").textContent = redPipelines;
    document.getElementById("stat-credited").textContent = credited;
  }

  function renderRow(issue) {
    const tr = document.createElement("tr");

    const statusVal = (issue.status && issue.status.value) || "unknown";
    const newCount = (issue.comments && issue.comments.new_since_last_check) || 0;

    let mrCell = "—";
    if (issue.mr && issue.mr.iid) {
      const pStatus = issue.mr.pipeline_status;
      const pLabel = issue.mr.pipeline_label;
      const pClass = pipelinePillClass(pStatus, pLabel);
      const mrUrl = `https://git.drupalcode.org/project/${issue.mr.project}/-/merge_requests/${issue.mr.iid}`;
      const pipelineText = pLabel || pStatus || issue.mr.state || "unknown";
      const pipelinePill = issue.mr.pipeline_url
        ? `<a href="${escapeHtml(issue.mr.pipeline_url)}" target="_blank" rel="noopener" class="pill ${pClass}">${escapeHtml(pipelineText)}</a>`
        : `<span class="pill ${pClass}">${escapeHtml(pipelineText)}</span>`;
      mrCell = `<a href="${mrUrl}" target="_blank" rel="noopener">!${escapeHtml(issue.mr.iid)}</a> ${pipelinePill}`;
    }

    let creditCell = '<span class="pill gray">not yet</span>';
    if (issue.credit && issue.credit.credited) {
      creditCell = '<span class="pill green">credited</span>';
    }

    const source = issue.source || "issueforge";
    const sourceCell = source === "imported"
      ? '<span class="pill gray">imported</span>'
      : '<span class="pill blue">IssueForge</span>';
    // A short step list renders inline fine, but a long one (the norm for
    // a full IssueForge session — preview through push) would otherwise
    // balloon every row's height and throw off the whole table's layout.
    // Collapse behind <details> past a threshold so the closed row stays
    // compact and only the one row a user expands grows.
    const STEPS_INLINE_THRESHOLD = 3;
    let whatWeDid;
    let copyText = "";
    if (issue.action_steps && issue.action_steps.length) {
      const steps = issue.action_steps;
      copyText = steps.map(s => `- ${s}`).join("\n");
      const list = `<ul class="steps-list">${steps.map(s => `<li>${escapeHtml(s)}</li>`).join("")}</ul>`;
      if (steps.length > STEPS_INLINE_THRESHOLD) {
        whatWeDid = `<details class="steps-details">`
          + `<summary>${escapeHtml(steps[0])} <span class="steps-more">(+${steps.length - 1} more)</span></summary>`
          + list
          + `</details>`;
      } else {
        whatWeDid = list;
      }
    } else {
      copyText = issue.action_summary || "";
      whatWeDid = escapeHtml(copyText
        || (source === "imported" ? "(imported credit — not worked via IssueForge)" : ""));
    }
    const copyBtn = copyText
      ? `<button type="button" class="copy-btn" title="Copy what we did" aria-label="Copy what we did">⧉</button>`
      : "";

    tr.innerHTML = `
      <td class="title-cell">
        <div class="issue-title"><a href="${escapeHtml(issue.issue_url)}" target="_blank" rel="noopener">${escapeHtml(issue.title || "(untitled)")}</a></div>
        <div class="issue-id">#${escapeHtml(issue.issue_id)} · ${escapeHtml(issue.project)}</div>
      </td>
      <td>${escapeHtml(issue.last_worked || "")}</td>
      <td><span class="pill ${pillClass(statusVal)}">${escapeHtml(statusVal)}</span>${newCount > 0 ? `<span class="new-badge">+${newCount} new</span>` : ""}</td>
      <td>${mrCell}</td>
      <td>${creditCell}</td>
      <td>${sourceCell}</td>
      <td class="steps-cell"><div class="steps-wrap">${copyBtn}${whatWeDid}</div></td>
    `;

    const btn = tr.querySelector(".copy-btn");
    if (btn) {
      // Bound via closure (not an inline HTML attribute) so arbitrary step
      // text — quotes, newlines, whatever a user typed — never has to be
      // escaped into an onclick string.
      btn.addEventListener("click", () => {
        copyToClipboard(copyText).then(() => {
          const original = btn.textContent;
          btn.textContent = "✓";
          btn.classList.add("copied");
          setTimeout(() => {
            btn.textContent = original;
            btn.classList.remove("copied");
          }, 1200);
        });
      });
    }
    return tr;
  }

  function copyToClipboard(text) {
    // navigator.clipboard requires a secure context — https:// or
    // http://localhost (the served mode) both qualify, but a plain
    // file:// page (the --no-server static fallback) does not, so that
    // API is silently unavailable there. Fall back to the classic
    // hidden-textarea + execCommand("copy") trick, which works from any
    // origin including file://.
    if (navigator.clipboard && window.isSecureContext) {
      return navigator.clipboard.writeText(text);
    }
    return new Promise((resolve, reject) => {
      const ta = document.createElement("textarea");
      ta.value = text;
      ta.style.position = "fixed";
      ta.style.opacity = "0";
      document.body.appendChild(ta);
      ta.select();
      try {
        document.execCommand("copy") ? resolve() : reject();
      } catch (e) {
        reject(e);
      } finally {
        document.body.removeChild(ta);
      }
    });
  }

  function render() {
    const issues = (data.issues || [])
      .filter(matchesFilter)
      .filter(matchesSearch)
      .sort(compareIssues);

    renderStats(data.issues || []);

    const tbody = document.getElementById("issue-rows");
    tbody.innerHTML = "";
    if (issues.length === 0) {
      document.getElementById("empty-state").style.display = "block";
      document.getElementById("issue-table").style.display = "none";
      return;
    }
    document.getElementById("empty-state").style.display = "none";
    document.getElementById("issue-table").style.display = "table";
    issues.forEach(issue => tbody.appendChild(renderRow(issue)));
  }

  function setRefreshBusy(busy, statusEl, btnEl) {
    btnEl.disabled = busy;
    btnEl.textContent = busy ? "Refreshing…" : btnEl.dataset.label;
  }

  function doRefresh() {
    const btn = document.getElementById("refresh-btn");
    const status = document.getElementById("refresh-status");
    btn.dataset.label = btn.dataset.label || "Refresh";
    setRefreshBusy(true, status, btn);
    status.style.display = "block";
    status.classList.remove("error");
    status.textContent = "Refreshing — this can take up to a minute…";

    fetch("/api/refresh", { method: "POST" })
      .then(r => r.json())
      .then(result => {
        status.textContent = result.message || (result.ok ? "Done." : "Refresh failed.");
        if (!result.ok) status.classList.add("error");
        return fetch("/api/data");
      })
      .then(r => r.ok ? r.json() : null)
      .then(freshData => {
        if (freshData) {
          data.issues = freshData.issues;
          data.generated_at = freshData.generated_at;
          document.getElementById("generated-at").textContent =
            data.generated_at ? `Last refreshed: ${data.generated_at}` : "Never refreshed";
          render();
        }
      })
      .catch(() => {
        status.textContent = "Refresh requires the local dashboard server — "
          + "run `python scripts/dashboard.py` to start it.";
        status.classList.add("error");
      })
      .finally(() => setRefreshBusy(false, status, btn));
  }

  function refreshGeneratedAtLabel() {
    document.getElementById("generated-at").textContent =
      data.generated_at ? `Last refreshed: ${data.generated_at}` : "Never refreshed";
  }

  function init() {
    refreshGeneratedAtLabel();

    document.getElementById("refresh-btn").addEventListener("click", doRefresh);

    if (servedMode) {
      fetch("/api/data")
        .then(r => r.ok ? r.json() : Promise.reject())
        .then(freshData => {
          data.issues = freshData.issues || [];
          data.generated_at = freshData.generated_at || null;
          refreshGeneratedAtLabel();
          render();
        })
        .catch(() => { render(); });
    }

    document.getElementById("search").addEventListener("input", (e) => {
      searchTerm = e.target.value.trim().toLowerCase();
      render();
    });

    document.querySelectorAll(".filter-btn").forEach(btn => {
      btn.addEventListener("click", () => {
        document.querySelectorAll(".filter-btn").forEach(b => b.classList.remove("active"));
        btn.classList.add("active");
        activeFilter = btn.dataset.filter;
        render();
      });
    });

    document.querySelectorAll("th[data-sort]").forEach(th => {
      th.addEventListener("click", () => {
        const key = th.dataset.sort;
        if (sortKey === key) {
          sortDir *= -1;
        } else {
          sortKey = key;
          sortDir = -1;
        }
        render();
      });
    });

    render();
  }

  document.addEventListener("DOMContentLoaded", init);
})();
