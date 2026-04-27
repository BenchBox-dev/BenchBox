import Router from "preact-router";
import { Layout } from "./components/Layout";
import { Home } from "./pages/Home";
import { BenchmarkIndex } from "./pages/BenchmarkIndex";
import { PlatformIndex } from "./pages/PlatformIndex";
import { ResultDetail } from "./pages/ResultDetail";
import { Compare } from "./pages/Compare";
import { Query } from "./pages/Query";
import { NotFound } from "./pages/NotFound";

export function App() {
  return (
    <Layout>
      <Router>
        <Home path="/results/" />
        <Compare path="/results/compare" />
        <Compare path="/results/compare/" />
        <Query path="/results/query" />
        <Query path="/results/query/" />
        <PlatformIndex path="/results/p/:platform/" />
        <ResultDetail path="/results/r/:resultId" />
        <BenchmarkIndex path="/results/:benchmark/" />
        <NotFound default />
      </Router>
    </Layout>
  );
}
