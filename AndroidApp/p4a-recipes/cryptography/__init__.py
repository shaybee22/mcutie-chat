"""p4a's cryptography recipe, plus an explicit link against libpython.

PyO3 builds the Rust extension (_rust.abi3.so) without linking libpython,
which works on desktop Linux but not on Android: the module fails to import
with "cannot locate symbol PyExc_TypeError". C extensions built by p4a
(e.g. _cffi_backend.so) link libpython3.X.so explicitly; this does the same.
Remove once upstream python-for-android links it.
"""
from pythonforandroid.recipes.cryptography import CryptographyRecipe


class CryptographyLinkPythonRecipe(CryptographyRecipe):

    def get_recipe_env(self, arch, **kwargs):
        env = super().get_recipe_env(arch, **kwargs)
        env["RUSTFLAGS"] += " -Clink-arg=-lpython{}".format(
            self.ctx.python_recipe.link_version)
        return env


recipe = CryptographyLinkPythonRecipe()
