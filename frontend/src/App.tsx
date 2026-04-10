import { BrowserRouter, Routes, Route } from "react-router-dom";
import Shell from "./components/layout/Shell";
import Dashboard from "./pages/Dashboard";
import RunDetail from "./pages/RunDetail";
import Compare from "./pages/Compare";
import Questions from "./pages/Questions";
import ReviewQueue from "./pages/ReviewQueue";
import Seed from "./pages/Seed";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<Shell />}>
          <Route index element={<Dashboard />} />
          <Route path="runs/:id" element={<RunDetail />} />
          <Route path="compare" element={<Compare />} />
          <Route path="questions" element={<Questions />} />
          <Route path="review" element={<ReviewQueue />} />
          <Route path="seed" element={<Seed />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
