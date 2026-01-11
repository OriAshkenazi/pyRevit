"""Validate pyRevit bundle.yaml files for structural integrity.

This script validates bundle.yaml files across the extension directories:
- Checks that layout references point to actual bundle directories
- Validates YAML syntax and structure
- Detects AI-generated or invalid layout entries

This validation is particularly important after bulk localization or AI-assisted
translations, which may introduce fake layout references like "analysis1", "analysis2",
etc., that don't correspond to actual bundle directories.

Usage:
    python dev/validate_bundles.py [--fix]
    python dev/validate_bundles.py --extensions-dir path/to/extensions
    
Options:
    --fix              Attempt to auto-fix invalid layout entries by scanning directories
    --extensions-dir   Path to extensions directory (default: extensions)

Examples:
    # Validate all bundle.yaml files
    python dev/validate_bundles.py
    
    # Validate and auto-fix issues
    python dev/validate_bundles.py --fix
    
Exit Codes:
    0 - All bundle.yaml files are valid
    1 - One or more bundle.yaml files have validation errors
"""

import os
import sys
from pathlib import Path
from typing import List, Dict, Tuple, Set
import yaml


# Bundle extensions that are valid in pyRevit
BUNDLE_EXTENSIONS = [
    '.pushbutton',
    '.pulldown', 
    '.stack',
    '.smartbutton',
    '.panelbutton',
    '.splitpushbutton',
    '.panel',
    '.tab',
    '.invokebutton',
    '.urlbutton',
    '.linkbutton',
    '.content',
    '.combobox',
    '.deprecate',
]


def find_bundle_yaml_files(base_dir: Path) -> List[Path]:
    """Find all bundle.yaml files in the extensions directory."""
    bundle_files = []
    for root, dirs, files in os.walk(base_dir):
        # Skip hidden directories and non-extension directories
        dirs[:] = [d for d in dirs if not d.startswith('.')]
        
        if 'bundle.yaml' in files:
            bundle_files.append(Path(root) / 'bundle.yaml')
    
    return bundle_files


def get_actual_bundle_items(bundle_dir: Path) -> Set[str]:
    """Get actual bundle items (without extensions) in a directory."""
    if not bundle_dir.exists():
        return set()
    
    items = set()
    for item in bundle_dir.iterdir():
        if item.name == 'bundle.yaml':
            continue
            
        # Check if it's a valid pyRevit bundle
        if item.is_dir():
            for ext in BUNDLE_EXTENSIONS:
                if item.name.endswith(ext):
                    # Strip extension to get layout name
                    name = item.name[:-len(ext)]
                    items.add(name)
                    break
    
    return items


def validate_bundle_layout(bundle_path: Path) -> Tuple[bool, List[str], Set[str]]:
    """Validate layout references in a bundle.yaml file.
    
    Returns:
        Tuple of (is_valid, error_messages, actual_items)
    """
    errors = []
    
    try:
        with open(bundle_path, 'r', encoding='utf-8') as f:
            bundle_data = yaml.safe_load(f)
    except Exception as e:
        return False, [f"Failed to parse YAML: {e}"], set()
    
    if not bundle_data:
        return True, [], set()  # Empty bundle is technically valid
    
    # Get layout if it exists
    layout = bundle_data.get('layout')
    if not layout:
        return True, [], set()  # No layout is valid (no explicit ordering)
    
    if not isinstance(layout, list):
        return False, ["'layout' field must be a list"], set()
    
    # Get actual bundle items in the directory
    bundle_dir = bundle_path.parent
    actual_items = get_actual_bundle_items(bundle_dir)
    
    # Validate each layout entry
    for layout_item in layout:
        if not isinstance(layout_item, str):
            errors.append(f"Layout item must be string, got: {type(layout_item)}")
            continue
        
        # Skip separators
        if layout_item.strip() == '-----':
            continue
        
        # Skip special UI markers (like '>>>>>' for visual grouping)
        if all(c in '><' for c in layout_item.strip()):
            continue
        
        # Extract base name from pyRevit special directives
        # Examples: "pyRevit[beforeall:]", "Templates[afterall:]", "Panel[before:Other]"
        base_name = layout_item
        if '[' in layout_item and ']' in layout_item:
            base_name = layout_item.split('[')[0]
        
        # Extract base name from layout titles
        # Examples: "Misc Tests[title:Third-Party\nUnit Tests]"
        if '[title:' in layout_item:
            base_name = layout_item.split('[title:')[0]
        
        # Check if base layout item exists in actual items
        if base_name not in actual_items:
            errors.append(
                f"Layout reference '{layout_item}' (base: '{base_name}') not found in directory. "
                f"Available items: {sorted(actual_items)}"
            )
    
    is_valid = len(errors) == 0
    return is_valid, errors, actual_items


def generate_fixed_layout(layout: List[str], actual_items: Set[str]) -> List[str]:
    """Generate a fixed layout by replacing invalid entries with actual items.
    
    Strategy:
    1. Keep valid entries in their original order
    2. Remove invalid entries
    3. Add missing items at the end
    """
    fixed_layout = []
    used_items = set()
    
    # First pass: keep valid entries
    for item in layout:
        if item == '-----':
            fixed_layout.append(item)
        elif item in actual_items:
            fixed_layout.append(item)
            used_items.add(item)
    
    # Second pass: add missing items
    missing_items = actual_items - used_items
    if missing_items:
        fixed_layout.extend(sorted(missing_items))
    
    return fixed_layout


def fix_bundle_layout(bundle_path: Path, actual_items: Set[str]) -> bool:
    """Attempt to fix invalid layout in a bundle.yaml file."""
    try:
        with open(bundle_path, 'r', encoding='utf-8') as f:
            content = f.read()
            
        bundle_data = yaml.safe_load(content)
        
        if not bundle_data or 'layout' not in bundle_data:
            return False
        
        # Generate fixed layout
        old_layout = bundle_data['layout']
        new_layout = generate_fixed_layout(old_layout, actual_items)
        
        if old_layout == new_layout:
            return False  # Nothing to fix
        
        bundle_data['layout'] = new_layout
        
        # Write back
        with open(bundle_path, 'w', encoding='utf-8') as f:
            yaml.safe_dump(
                bundle_data,
                f,
                default_flow_style=False,
                allow_unicode=True,
                sort_keys=False
            )
        
        return True
        
    except Exception as e:
        print(f"  Failed to fix: {e}")
        return False


def main():
    """Main validation entry point."""
    import argparse
    
    parser = argparse.ArgumentParser(description='Validate pyRevit bundle.yaml files')
    parser.add_argument('--fix', action='store_true', help='Attempt to auto-fix invalid entries')
    parser.add_argument('--extensions-dir', default='extensions', help='Path to extensions directory')
    args = parser.parse_args()
    
    # Get repository root (parent of dev directory)
    script_dir = Path(__file__).parent
    repo_root = script_dir.parent
    extensions_dir = repo_root / args.extensions_dir
    
    if not extensions_dir.exists():
        print(f"Error: Extensions directory not found: {extensions_dir}")
        return 1
    
    print(f"Validating bundle.yaml files in: {extensions_dir}")
    print()
    
    # Find all bundle.yaml files
    bundle_files = find_bundle_yaml_files(extensions_dir)
    print(f"Found {len(bundle_files)} bundle.yaml files")
    print()
    
    # Validate each file
    invalid_count = 0
    fixed_count = 0
    
    for bundle_path in sorted(bundle_files):
        relative_path = bundle_path.relative_to(repo_root)
        is_valid, errors, actual_items = validate_bundle_layout(bundle_path)
        
        if not is_valid:
            invalid_count += 1
            print(f"❌ {relative_path}")
            for error in errors:
                print(f"   {error}")
            
            if args.fix:
                print(f"   Attempting to fix...")
                if fix_bundle_layout(bundle_path, actual_items):
                    print(f"   ✅ Fixed!")
                    fixed_count += 1
                else:
                    print(f"   ⚠️  Could not auto-fix")
            print()
    
    # Summary
    if invalid_count == 0:
        print("✅ All bundle.yaml files are valid!")
        return 0
    else:
        print(f"\n{'='*60}")
        print(f"Found {invalid_count} invalid bundle.yaml file(s)")
        if args.fix:
            print(f"Fixed {fixed_count} file(s)")
            if fixed_count < invalid_count:
                print(f"{invalid_count - fixed_count} file(s) require manual review")
        else:
            print("Run with --fix to attempt automatic fixes")
        print(f"{'='*60}")
        return 1


if __name__ == '__main__':
    sys.exit(main())
