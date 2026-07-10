import unittest

from jobspy.scrapers.tokyodev import TokyoDev


class _ListingLocator:
    def __init__(self, markup: str) -> None:
        self.markup = markup

    def inner_html(self) -> str:
        return self.markup


class _ListingPage:
    def __init__(self, markup: str) -> None:
        self.markup = markup

    def locator(self, selector: str) -> _ListingLocator:
        assert selector == "ul.list-inside"
        return _ListingLocator(self.markup)


class TokyoDevScraperTestCase(unittest.TestCase):
    def test_seed_extraction_uses_one_listing_markup_snapshot(self) -> None:
        markup = """
        <li>
          <h3><a>Example Co</a></h3>
          <div data-collapsable-list-target="item">
            <div class="text-lg font-bold"><a href="/jobs/engineer">Engineer</a></div>
            <div class="flex gap-2">
              <a href="/jobs/salary-data">¥8M ~ ¥12M</a>
              <a href="/jobs?remote_policy=fully_remote">Fully Remote</a>
              <a href="/jobs?skill=python">Python</a>
            </div>
          </div>
        </li>
        """

        seeds = TokyoDev()._extract_seeds_from_list_page(_ListingPage(markup), 1)

        self.assertEqual(len(seeds), 1)
        self.assertEqual(seeds[0].job_url, "https://www.tokyodev.com/jobs/engineer")
        self.assertEqual(seeds[0].company_name, "Example Co")
        self.assertTrue(seeds[0].is_remote_hint)
        self.assertEqual(seeds[0].salary_text_hint, "¥8M ~ ¥12M")
        self.assertEqual(seeds[0].skills, ["Python"])


if __name__ == "__main__":
    unittest.main()
