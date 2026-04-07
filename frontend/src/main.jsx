import React, { useContext, useEffect, useState } from "react";
import ReactDOM from "react-dom/client";
import axios from "axios";
import { AddonProvider, AddonContext } from "@ynput/ayon-react-addon-provider";

import "@ynput/ayon-react-components/dist/style.css";

import App from "./App";
import "./debugly.css";

function Shell() {
  const ctx = useContext(AddonContext);
  const accessToken = ctx?.accessToken;
  const addonName = ctx?.addonName;
  const addonVersion = ctx?.addonVersion;
  const [tokenSet, setTokenSet] = useState(false);

  useEffect(() => {
    if (accessToken && !tokenSet) {
      axios.defaults.headers.common.Authorization = `Bearer ${accessToken}`;
      setTokenSet(true);
    }
  }, [accessToken, tokenSet]);

  if (!tokenSet) {
    return <div className="debugly-loading">Loading…</div>;
  }
  if (!addonName || !addonVersion) {
    return <div className="debugly-loading">Addon context unavailable</div>;
  }

  const baseUrl = `${window.location.origin}/api/addons/${addonName}/${addonVersion}`;
  return <App baseUrl={baseUrl} />;
}

ReactDOM.createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <AddonProvider debug>
      <Shell />
    </AddonProvider>
  </React.StrictMode>
);
