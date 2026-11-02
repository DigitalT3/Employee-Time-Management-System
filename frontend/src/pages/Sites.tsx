import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { DeviceCreated, Gate, Site, SiteSettings } from "../api/types";
import { useAuth } from "../auth";
import { ErrorBanner, useLoad } from "../components/common";
import { useI18n } from "../i18n";

function SitePanel({ site, canManage, onChange }: { site: Site; canManage: boolean; onChange: () => void }) {
  const { t } = useI18n();
  const gates = useLoad(() => api.gates(site.id), [site.id]);
  const devices = useLoad(() => api.devices(), []);
  const settings = useLoad<SiteSettings>(() => api.siteSettings(site.id), [site.id]);
  const [siteName, setSiteName] = useState(site.name);
  const [timezone, setTimezone] = useState(site.timezone);
  const [gateName, setGateName] = useState("");
  const [editingGate, setEditingGate] = useState<Gate | null>(null);
  const [gateEditName, setGateEditName] = useState("");
  const [devName, setDevName] = useState("");
  const [devGate, setDevGate] = useState("");
  const [created, setCreated] = useState<DeviceCreated | null>(null);
  const [dup, setDup] = useState("");
  const [cutoff, setCutoff] = useState("");
  const [error, setError] = useState<string | null>(null);

  const run = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
      setError(null);
    } catch (cause) {
      setError((cause as Error).message);
    }
  };

  const gateIds = new Set((gates.data ?? []).map((gate) => gate.id));
  const siteDevices = (devices.data ?? []).filter((device) => device.site_id === site.id);

  return (
    <div className="card">
      <div className="row">
        <h2>{site.code} – {site.name}</h2>
        <span className={`badge ${site.is_active ? "ok" : "off"}`}>{site.is_active ? t("common.active") : t("common.inactive")}</span>
        {canManage && (
          <button onClick={() => void run(async () => {
            await api.updateSite(site.id, { is_active: !site.is_active });
            onChange();
          })}>
            {site.is_active ? t("common.deactivate") : t("common.activate")}
          </button>
        )}
      </div>
      <ErrorBanner message={error ?? gates.error ?? settings.error} />

      <h3>{t("common.edit")}</h3>
      <form className="row" onSubmit={(event: FormEvent) => {
        event.preventDefault();
        void run(async () => {
          await api.updateSite(site.id, { name: siteName, timezone });
          onChange();
        });
      }}>
        <label>{t("sites.siteName")}
          <input value={siteName} disabled={!canManage} onChange={(event) => setSiteName(event.target.value)} required />
        </label>
        <label>{t("common.timezone")}
          <input value={timezone} disabled={!canManage} onChange={(event) => setTimezone(event.target.value)} required aria-describedby={`${site.id}-timezone-help`} />
        </label>
        <span id={`${site.id}-timezone-help`} className="muted">{t("sites.timezoneHelp")}</span>
        {canManage && <button type="submit">{t("common.save")}</button>}
      </form>

      <h3>{t("sites.settings")}</h3>
      {settings.data && (
        <form className="row" onSubmit={(event: FormEvent) => {
          event.preventDefault();
          void run(async () => {
            await api.saveSiteSettings(site.id, {
              duplicate_window_seconds: Number(dup || settings.data!.duplicate_window_seconds),
              missing_out_cutoff_time: cutoff || settings.data!.missing_out_cutoff_time,
            });
            await settings.reload();
          });
        }}>
          <label>{t("sites.duplicateWindow")}
            <input type="number" min={0} max={3600} disabled={!canManage}
              value={dup || settings.data.duplicate_window_seconds} onChange={(event) => setDup(event.target.value)} />
          </label>
          <label>{t("sites.cutoff")}
            <input type="time" step={1} disabled={!canManage}
              value={cutoff || settings.data.missing_out_cutoff_time} onChange={(event) => setCutoff(event.target.value)} />
          </label>
          {canManage && <button type="submit">{t("common.save")}</button>}
        </form>
      )}

      <h3>{t("sites.gates")}</h3>
      <ul>
        {(gates.data ?? []).map((gate) => (
          <li key={gate.id}>
            {editingGate?.id === gate.id ? (
              <form className="row" onSubmit={(event) => {
                event.preventDefault();
                void run(async () => {
                  await api.updateGate(gate.id, { name: gateEditName });
                  setEditingGate(null);
                  await gates.reload();
                });
              }}>
                <label>{t("sites.gateName")}
                  <input value={gateEditName} onChange={(event) => setGateEditName(event.target.value)} required autoFocus />
                </label>
                <button type="submit">{t("common.save")}</button>
                <button type="button" onClick={() => setEditingGate(null)}>{t("common.cancel")}</button>
              </form>
            ) : (
              <>
                {gate.name} <span className={`badge ${gate.is_active ? "ok" : "off"}`}>{gate.is_active ? t("common.active") : t("common.inactive")}</span>
                {canManage && <>
                  <button onClick={() => {
                    setEditingGate(gate);
                    setGateEditName(gate.name);
                  }}>{t("common.edit")}</button>
                  <button onClick={() => void run(async () => {
                    await api.updateGate(gate.id, { is_active: !gate.is_active });
                    await gates.reload();
                  })}>
                    {gate.is_active ? t("common.deactivate") : t("common.activate")}
                  </button>
                </>}
              </>
            )}
          </li>
        ))}
      </ul>
      {canManage && (
        <form className="row" onSubmit={(event) => {
          event.preventDefault();
          void run(async () => {
            await api.createGate(site.id, gateName);
            setGateName("");
            await gates.reload();
          });
        }}>
          <input value={gateName} onChange={(event) => setGateName(event.target.value)} placeholder={t("sites.newGate")} required />
          <button type="submit">{t("common.create")}</button>
        </form>
      )}

      <h3>{t("sites.devices")}</h3>
      <ul>
        {siteDevices.map((device) => (
          <li key={device.id}>{device.name} <span className={`badge ${device.is_active ? "ok" : "off"}`}>{device.is_active ? t("common.active") : t("common.inactive")}</span>
            {canManage && <button onClick={() => void run(async () => {
              await api.setDeviceActive(device.id, !device.is_active);
              await devices.reload();
            })}>
              {device.is_active ? t("common.deactivate") : t("common.activate")}
            </button>}
          </li>
        ))}
      </ul>
      {canManage && (gates.data?.length ?? 0) > 0 && (
        <form className="row" onSubmit={(event) => {
          event.preventDefault();
          void run(async () => {
            const gate = devGate && gateIds.has(devGate) ? devGate : gates.data![0].id;
            setCreated(await api.createDevice(devName, gate));
            setDevName("");
            await devices.reload();
          });
        }}>
          <input value={devName} onChange={(event) => setDevName(event.target.value)} placeholder={t("sites.deviceName")} required />
          <select value={devGate || gates.data![0].id} onChange={(event) => setDevGate(event.target.value)} aria-label={t("sites.gate")}>
            {gates.data!.map((gate) => <option key={gate.id} value={gate.id}>{gate.name}</option>)}
          </select>
          <button type="submit">{t("sites.newDevice")}</button>
        </form>
      )}
      {created && (
        <div className="notice">
          <p>{t("sites.deviceToken")}: <code>{created.device_token}</code></p>
          <Link to="/scanner/setup" state={{ token: created.device_token }}>{t("sites.openSetup")}</Link>
        </div>
      )}
    </div>
  );
}

/** Site, gate, settings and scanner-device administration. */
export default function Sites() {
  const { t } = useI18n();
  const { can } = useAuth();
  const canManage = can("sites.manage");
  const sites = useLoad(() => api.sites(), []);
  const [code, setCode] = useState("");
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);

  return (
    <section>
      <h1>{t("sites.title")}</h1>
      <ErrorBanner message={error ?? sites.error} />
      {canManage && (
        <form className="row" onSubmit={async (event) => {
          event.preventDefault();
          try {
            await api.createSite({ code, name });
            setCode("");
            setName("");
            await sites.reload();
            setError(null);
          } catch (cause) {
            setError((cause as Error).message);
          }
        }}>
          <input value={code} onChange={(event) => setCode(event.target.value)} placeholder={t("common.code")} required />
          <input value={name} onChange={(event) => setName(event.target.value)} placeholder={t("common.name")} required />
          <button className="primary" type="submit">{t("sites.new")}</button>
        </form>
      )}
      {(sites.data ?? []).map((site) => <SitePanel key={site.id} site={site} canManage={canManage} onChange={() => void sites.reload()} />)}
    </section>
  );
}
