import { NavLink } from "react-router-dom";
import { colors, fonts } from "../../theme";

const navItems = [
  { to: "/", label: "Dashboard", accent: colors.runs },
  { to: "/runs", label: "Runs", accent: colors.runs },
  { to: "/compare", label: "Compare", accent: colors.metrics },
  { to: "/questions", label: "Questions", accent: colors.questions },
  { to: "/review", label: "Review Queue", accent: colors.review },
  { to: "/seed", label: "Seeder", accent: colors.seed },
];

export default function Sidebar() {
  return (
    <nav style={{
      width: 200, minHeight: "100vh", background: colors.surface,
      borderRight: `1px solid ${colors.border}`,
      display: "flex", flexDirection: "column", padding: "32px 0",
      position: "fixed", left: 0, top: 0, bottom: 0, zIndex: 10,
    }}>
      <div style={{ padding: "0 24px 32px", fontFamily: fonts.heading, fontSize: 18, fontWeight: 700 }}>
        T2S Eval
      </div>
      {navItems.map(({ to, label, accent }) => (
        <NavLink
          key={to}
          to={to}
          end={to === "/"}
          style={({ isActive }) => ({
            display: "block", padding: "10px 24px",
            color: isActive ? accent : colors.textMuted,
            textDecoration: "none",
            fontFamily: fonts.body, fontSize: 14, fontWeight: 500,
            borderLeft: isActive ? `3px solid ${accent}` : "3px solid transparent",
            background: isActive ? `${accent}12` : "transparent",
            transition: "all 0.15s",
          })}
        >
          {label}
        </NavLink>
      ))}
    </nav>
  );
}
