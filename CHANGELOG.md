**0.1.0** - Initial Release

**0.1.1** - Automated Real Release

**0.1.2** - README.md update

**0.1.3** - Performance Updates

No longer uses openapi-schema-pydantic, so should be more forgiving of parts of the schema we don't care about.  Does
lazy_loading of each path when parsing schema (was running into out-of-memory errors).  More efficient use of caches
so it can deal with extra-long lists of paths better

**0.1.4** - Add PyBugsOpenAI to CI/CD

Also, make CI/CD caching smarter
