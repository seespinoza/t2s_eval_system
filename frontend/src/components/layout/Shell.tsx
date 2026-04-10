import { Outlet } from "react-router-dom";
import Sidebar from "./Sidebar";
import GridTexture from "./GridTexture";
import { colors } from "../../theme";

export default function Shell() {
  return (
    <div style={{ background: colors.bg, minHeight: "100vh" }}>
      <GridTexture />
      <Sidebar />
      <main style={{ marginLeft: 200, padding: "32px", position: "relative", zIndex: 1 }}>
        <Outlet />
      </main>
    </div>
  );
}
