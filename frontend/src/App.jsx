import React, { useEffect, useState } from "react";
import axios from "axios";
import "./debugly.css";

async function fetchAttachmentBlob(baseUrl, zipFile, basename) {
  const url = `${baseUrl}/issues/${encodeURIComponent(zipFile)}/attachment/${encodeURIComponent(basename)}`;
  const res = await axios.get(url, { responseType: "blob" });
  return res.data;
}

function App({ baseUrl }) {
  const [issues, setIssues] = useState([]);
  const [selected, setSelected] = useState(null);
  const [error, setError] = useState(null);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    axios
      .get(`${baseUrl}/issues`)
      .then((res) => {
        if (!cancelled) {
          setIssues(Array.isArray(res.data) ? res.data : []);
        }
      })
      .catch((e) => {
        if (!cancelled) {
          setError(e?.response?.data?.detail || e?.message || "Failed to load issues");
          setIssues([]);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [baseUrl]);

  const openBlob = async (zipFile, basename, downloadName) => {
    try {
      const blob = await fetchAttachmentBlob(baseUrl, zipFile, basename);
      const obj = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = obj;
      a.download = downloadName || basename;
      a.rel = "noopener";
      a.click();
      URL.revokeObjectURL(obj);
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || "Download failed");
    }
  };

  const viewBlobInTab = async (zipFile, basename) => {
    try {
      const blob = await fetchAttachmentBlob(baseUrl, zipFile, basename);
      const obj = URL.createObjectURL(blob);
      window.open(obj, "_blank", "noopener,noreferrer");
      setTimeout(() => URL.revokeObjectURL(obj), 60_000);
    } catch (e) {
      setError(e?.response?.data?.detail || e?.message || "Open failed");
    }
  };

  const handleSelect = (issue) => {
    setSelected(issue);
  };

  return (
    <div>
      <h1>Debugly Issues</h1>
      {error && (
        <p className="debugly-error" role="alert">
          {error}
        </p>
      )}
      <div style={{ display: "flex" }}>
        <div style={{ flex: 1, maxWidth: 350 }}>
          {issues.map((issue) => (
            <div
              key={issue.zip_file || issue.timestamp}
              className={`card${selected && selected.zip_file === issue.zip_file ? " selected" : ""}`}
              onClick={() => handleSelect(issue)}
              onKeyDown={(ev) => {
                if (ev.key === "Enter" || ev.key === " ") {
                  ev.preventDefault();
                  handleSelect(issue);
                }
              }}
              role="button"
              tabIndex={0}
            >
              <b>{issue.timestamp}</b>
              <br />
              <b>User:</b> {issue.collected_data?.user || ""}
              <br />
              <b>Message:</b> {issue.user_message}
            </div>
          ))}
        </div>
        <div style={{ flex: 2, marginLeft: 20 }}>
          {selected && (
            <div className="issue-details">
              <h2>Issue Details</h2>
              <pre>{JSON.stringify(selected, null, 2)}</pre>
              <div>
                <b>Logs:</b>{" "}
                {(selected.attachments || []).map((f) => {
                  const base = f.split("/").pop();
                  return (
                    <button
                      key={f}
                      type="button"
                      className="debugly-link-btn"
                      onClick={() => openBlob(selected.zip_file, base, base)}
                    >
                      {base}
                    </button>
                  );
                })}
              </div>
              <div style={{ marginTop: 10 }}>
                <b>Screenshot:</b>{" "}
                {selected.screenshot ? (
                  <button
                    type="button"
                    className="debugly-link-btn"
                    onClick={() =>
                      viewBlobInTab(selected.zip_file, selected.screenshot.split("/").pop())
                    }
                  >
                    View
                  </button>
                ) : (
                  "None"
                )}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default App;
