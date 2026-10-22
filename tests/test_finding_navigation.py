from html.parser import HTMLParser
import json
import unittest

from rankprobe.audit import audit_run, compare_runs
from rankprobe.model import Protocol, Row
from rankprobe.report import render_html


class Element:
    def __init__(self, tag="", attrs=(), parent=None):
        self.tag, self.attrs, self.parent = tag, dict(attrs), parent
        self.children = []

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, Element):
                yield from child.walk()

    def text(self):
        return "".join(c.text() if isinstance(c, Element) else c for c in self.children)

    def closed_parents(self):
        node = self.parent
        while node is not None:
            if node.tag == "details" and "open" not in node.attrs:
                yield node
            node = node.parent


class Page(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.root = self.node = Element()
        self.feed(source)
        self.ids = {n.attrs["id"]: n for n in self.root.walk() if "id" in n.attrs}

    def handle_starttag(self, tag, attrs):
        element = Element(tag, attrs, self.node)
        self.node.children.append(element)
        if tag not in {"meta", "link", "br", "hr", "img", "input"}:
            self.node = element

    def handle_endtag(self, tag):
        node = self.node
        while node.parent is not None:
            if node.tag == tag:
                self.node = node.parent
                return
            node = node.parent

    def handle_data(self, data):
        self.node.children.append(data)

    def finding_links(self, index):
        return [n for n in self.ids[f"finding-{index}"].walk() if n.tag == "a"]


class FindingNavigationTests(unittest.TestCase):
    def test_tie_finding_opens_the_right_run_diagnostic_without_hidden_ancestors(self):
        report = compare_runs({
            "exact": [Row("q", "a", 2, 1), Row("q", "b", 1, 0)],
            'round<&"': [Row("q", "a", 1, 1), Row("q", "b", 1, 0)],
        }, Protocol(cutoffs=(1,)))
        original = json.dumps(report, sort_keys=True)
        page = Page(render_html(report))
        index = next(i for i, f in enumerate(report["findings"])
                     if f["code"] == "score_ties")
        links = page.finding_links(index)
        target = next(link.attrs["href"][1:] for link in links
                      if "同分影响" in link.text())
        self.assertIn('round<&"', next(link.text() for link in links
                                      if "同分影响" in link.text()))
        diagnostic = page.ids[target]
        self.assertFalse(list(diagnostic.closed_parents()))
        self.assertIn('round<&"', diagnostic.text())
        self.assertIn("Metric bounds", diagnostic.text())
        self.assertIn("Input order probe", diagnostic.text())
        self.assertNotIn("<script", render_html(report))
        self.assertEqual(json.dumps(report, sort_keys=True), original)

    def test_evidence_is_one_disclosure_away_from_the_finding(self):
        report = audit_run([Row("query-1", "a", 1), Row("query-1", "b", 1)],
                           Protocol(cutoffs=(1,)))
        index = next(i for i, f in enumerate(report["findings"])
                     if f["code"] == "score_ties")
        page = Page(render_html(report))
        evidence = page.ids[f"finding-{index}-evidence"]
        self.assertEqual(evidence.tag, "details")
        self.assertFalse(list(evidence.closed_parents()))
        self.assertIn("query-1", evidence.text())
        sample_cell = next(node for node in evidence.walk()
                           if node.tag == "td" and node.text() == "query-1")
        self.assertEqual(list(sample_cell.closed_parents()), [evidence])
        self.assertIn("Judgments known", evidence.text())
        self.assertIn("No", evidence.text())
        guide = page.ids["score-export-recheck"].text()
        self.assertIn("原始分数本来就相同", guide)
        self.assertIn("没有保留原始分数", guide)
        self.assertIn("警告全部消失", guide)

    def test_pair_finding_targets_its_own_pair_in_a_three_run_report(self):
        report = compare_runs({
            "a": [Row("q1", "a", 2, 1), Row("q1", "b", 1, 0)],
            "b": [Row("q1", "a", 2, 1), Row("q1", "b", 1, 0)],
            "c": [Row("q1", "a", 2, 1), Row("q1", "b", 1, 0), Row("q2", "c", 1, 0)],
        }, Protocol(cutoffs=(1,)))
        page = Page(render_html(report))
        index = next(i for i, f in enumerate(report["findings"])
                     if f["code"] == "query_coverage_mismatch" and f["evidence"]["left"] == "b")
        links = page.finding_links(index)
        link = next(link for link in links if "这两份结果" in link.text())
        self.assertEqual(link.attrs["href"], "#pair-2")
        self.assertIn("b → c", page.ids["pair-2"].text())

    def test_unknown_labels_and_duplicates_link_to_the_affected_run(self):
        report = compare_runs({
            "complete": [Row("q", "a", 2, 1), Row("q", "b", 1, 0)],
            "partial": [Row("q", "a", 2, 1), Row("q", "a", 1, 1), Row("q", "b", 1)],
        }, Protocol(cutoffs=(1,)))
        page = Page(render_html(report))
        for code, label in [("unknown_judgments", "分数与查询范围"),
                            ("duplicate_candidates", "重复项影响")]:
            with self.subTest(code=code):
                index = next(i for i, f in enumerate(report["findings"])
                             if f["code"] == code)
                link = next(link for link in page.finding_links(index) if label in link.text())
                target = page.ids[link.attrs["href"][1:]]
                self.assertFalse(list(target.closed_parents()))
                self.assertIn("partial", target.text())

    def test_sparse_and_truncated_reports_never_link_to_missing_targets(self):
        reports = [
            {"runs": {str(i): {"audit": {"tie_analysis": {"status": "checked"}}}
                      for i in range(62)},
             "findings": [{"code": "score_ties", "run_name": "61", "evidence": {}}]},
            {"pairs": [{"left": "a", "right": "b"}],
             "findings": [{"code": "score_ties", "run_name": "missing"}]},
            {"findings": [{"code": "future_check", "evidence": {"note": "<svg/onload=alert(1)>"}}]},
        ]
        for report in reports:
            with self.subTest(report=report):
                source = render_html(report)
                page = Page(source)
                ids = [n.attrs["id"] for n in page.root.walk() if "id" in n.attrs]
                self.assertEqual(len(ids), len(set(ids)))
                for node in page.root.walk():
                    href = node.attrs.get("href", "")
                    if href.startswith("#"):
                        self.assertIn(href[1:], page.ids)
                self.assertNotIn("<svg/", source)


if __name__ == "__main__":
    unittest.main()
