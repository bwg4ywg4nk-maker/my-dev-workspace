path = "tests/test_milestone3_phase3c2b_activation.py"
with open(path, "r") as f:
    code = f.read()

# Replace the broken LayoutProfile macro line with direct Python string formatting using build_id and runtime_id variables
# Or fix the C string literal so it correctly concatenates quotes around BUILD_ID and RUNTIME_ID.
# In C, to get a string literal containing quotes around a macro: ", \"" BUILD_ID "\", \"" RUNTIME_ID "\")\n"

old_target = 'p = layout.LayoutProfile(layout._NAME, 1, font, \'12.3.0\', \'2.14.3\', '
# Let's target the full broken line snippet and replace it with clean, direct python-side formatting:
