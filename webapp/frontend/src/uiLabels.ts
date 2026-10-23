const labels: Record<string, string> = {
  EA: "Enterprise architecture",
  ERD: "Entity relationships",
  OrgChart: "Organization chart",
  Flowchart: "Flowchart",
  data_io: "Data input / output",
  start_end: "Start / end",
  e_stop: "Emergency stop",
  dcdc_converter: "DC/DC converter",
  eth_switch: "Ethernet switch",
  vpn_tunnel: "VPN tunnel",
};

/** Presentation only: callers keep the original identifier in API payloads. */
export function humanLabel(identifier: string): string {
  const known = labels[identifier];
  if (known) return known;
  const words = identifier
    .replace(/([a-z\d])([A-Z])/g, "$1 $2")
    .replace(/[_-]+/g, " ")
    .trim();
  return words ? words[0].toUpperCase() + words.slice(1) : "Other";
}
