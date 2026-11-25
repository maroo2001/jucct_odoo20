from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
import csv
import base64
import io
from datetime import datetime, date
import chardet
import mimetypes
from io import BytesIO
import logging

# إضافة المكتبات المطلوبة لملفات Excel
try:
    import openpyxl
    from openpyxl import Workbook, load_workbook
    from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
    EXCEL_SUPPORT = True
except ImportError:
    EXCEL_SUPPORT = False
    _logger.warning("openpyxl library not installed. Excel support will not work.")

try:
    import xlsxwriter
    XLSXWRITER_SUPPORT = True
except ImportError:
    XLSXWRITER_SUPPORT = False
    _logger.warning("xlsxwriter library not installed. Alternative Excel generation not available.")

_logger = logging.getLogger(__name__)


class StudentBulkImport(models.TransientModel):
    _name = 'student.bulk.import'
    _description = 'Bulk Import Students and Enrolments'

    import_file = fields.Binary(string=_('Import File'))
    file_name = fields.Char(string=_('File Name'))
    import_type = fields.Selection([
        ('students', _('Students Only')),
        ('both', _('Students and Enrolments'))
    ], string=_('Import Type'), default='both', required=True)

    total_rows = fields.Integer(readonly=True)
    imported_students = fields.Integer(readonly=True)
    imported_enrolments = fields.Integer(readonly=True)
    skipped_enrolments = fields.Integer(readonly=True, string=_('Skipped Enrolments'))
    error_count = fields.Integer(readonly=True)
    error_log = fields.Text(readonly=True)
    state = fields.Selection([
        ('draft', _('Draft')),
        ('imported', _('Imported')),
        ('error', _('Error'))
    ], default='draft', readonly=True)

    def _get_import_file_bytes(self):
        """Return the uploaded file as raw bytes.

        Odoo 19.2+/20 binary fields hold raw bytes (``BinaryValue`` in 20) instead of base64;
        older values are base64. Handle both.
        """
        value = self.import_file
        content = getattr(value, 'content', value)
        if isinstance(content, str):
            content = content.encode()
        try:
            return base64.b64decode(content, validate=True)
        except Exception:
            return bytes(content)

    def _get_field_mappings(self):
        return {
            'national_id': ['national_id', 'الرقم الوطني', 'رقم وطني', 'الرقم', 'رقم'],
            'name': ['name', 'الاسم', 'اسم', 'الأسم'],
            'email': ['email', 'البريد الإلكتروني', 'بريد الكتروني', 'e-mail', 'البريد', 'بريد'],
            'phone': ['phone', 'رقم الهاتف', 'هاتف', 'الهاتف', 'الجوال'],
            'date_of_birth': ['date_of_birth', 'تاريخ الميلاد', 'تاريخ ميلاد', 'الميلاد', 'ميلاد'],
            'university_id': ['university_id', 'student_id', 'رقم الطالب', 'رقم طالب', 'الطالب'],
            'country_code': ['country_code', 'كود الدولة', 'رمز الدولة', 'country', 'كود دولة', 'الدولة'],
            'class_offering_code': ['class_offering_code', 'رمز البرنامج المقدم', 'رمز البرنامج', 'كود البرنامج', 'البرنامج'],
            'year': ['year', 'السنة', 'العام', 'سنة'],
            'semester': ['semester', 'الفصل', 'الفصل الدراسي', 'فصل']
        }

    def _normalize_field_name(self, field_name):
        if not field_name:
            return ''
        
        if isinstance(field_name, str) and field_name.startswith('\ufeff'):
            field_name = field_name[1:]
        
        field_name = str(field_name).strip()
        field_name = field_name.strip('"\'')
        field_name = ' '.join(field_name.split())
        
        return field_name

    def _detect_encoding(self, file_content):
        encodings_to_try = [
            'utf-8-sig',
            'utf-8',
            'windows-1256',
            'cp1256',
            'iso-8859-6',
            'latin-1'
        ]
        
        for encoding in encodings_to_try:
            try:
                decoded = file_content.decode(encoding)
                return encoding
            except (UnicodeDecodeError, AttributeError):
                continue
        
        return 'utf-8-sig'

    def _decode_file_content(self, file_content):
        encoding = self._detect_encoding(file_content)
        
        try:
            return file_content.decode(encoding)
        except UnicodeDecodeError:
            for enc in ['utf-8-sig', 'utf-8', 'windows-1256', 'cp1256', 'latin-1']:
                try:
                    return file_content.decode(enc)
                except:
                    continue
            return file_content.decode('utf-8', errors='ignore')

    def _map_csv_row(self, row):
        field_mappings = self._get_field_mappings()
        mapped_row = {}
        
        for csv_header, value in row.items():
            normalized_header = self._normalize_field_name(csv_header)
            
            found = False
            for std_field, aliases in field_mappings.items():
                for alias in aliases:
                    normalized_alias = self._normalize_field_name(alias)
                    if normalized_header == normalized_alias:
                        mapped_row[std_field] = value
                        found = True
                        break
                if found:
                    break
            
            if not found:
                mapped_row[csv_header] = value
        
        return mapped_row

    def _read_excel_file(self, file_content):
        try:
            if not EXCEL_SUPPORT:
                raise UserError(_('Please install openpyxl library: pip install openpyxl'))
            
            excel_file = BytesIO(file_content)
            workbook = load_workbook(excel_file, data_only=True)
            sheet = workbook.active
            
            rows = []
            headers = []
            
            # قراءة الـ headers من الصف الأول
            for cell in sheet[1]:
                headers.append(str(cell.value).strip() if cell.value is not None else '')
            
            # قراءة باقي الصفوف
            for row in sheet.iter_rows(min_row=2, values_only=True):
                row_dict = {}
                for col_idx, cell_value in enumerate(row):
                    if col_idx < len(headers):
                        if cell_value is None:
                            value = ''
                        elif isinstance(cell_value, datetime):
                            value = cell_value.strftime('%d-%m-%Y')
                        elif isinstance(cell_value, date):
                            value = cell_value.strftime('%d-%m-%Y')
                        else:
                            value = str(cell_value).strip()
                        row_dict[headers[col_idx]] = value
                
                rows.append(row_dict)
            
            return rows
            
        except Exception as e:
            _logger.error("Error reading Excel file: %s", str(e))
            raise UserError(_('Error reading Excel file: %s') % str(e))

    def _read_csv_file(self, file_content):
        try:
            file_string = self._decode_file_content(file_content)
            csv_data = io.StringIO(file_string)
            
            sample = csv_data.read(2048)
            csv_data.seek(0)
            
            delimiters = [',', ';', '\t', '|']
            delimiter_counts = {delim: sample.count(delim) for delim in delimiters}
            best_delimiter = max(delimiter_counts.items(), key=lambda x: x[1])[0]
            
            dialect = csv.excel()
            dialect.delimiter = best_delimiter
        except:
            dialect = csv.excel()
        
        csv_reader = csv.DictReader(csv_data, dialect=dialect)
        return list(csv_reader)

    def action_download_template(self):
        """Download CSV or Excel template"""
        import_type = self.import_type or 'both'
        
        user_lang = self.env.user.lang or 'en_US'
        is_arabic = user_lang.startswith('ar')
        
        if is_arabic:
            columns = []
            if import_type in ['students', 'both']:
                columns.extend([
                    'الرقم الوطني',
                    'الاسم',
                    'البريد الإلكتروني',
                    'الهاتف',
                    'تاريخ الميلاد',
                    'رقم الطالب',
                    'كود الدولة'
                ])
            if import_type == 'both':
                columns.extend([
                    'رمز البرنامج المقدم',
                    'السنة',
                    'الفصل'
                ])
        else:
            columns = []
            if import_type in ['students', 'both']:
                columns.extend([
                    'national_id',
                    'name',
                    'email',
                    'phone',
                    'date_of_birth',
                    'university_id',
                    'country_code'
                ])
            if import_type == 'both':
                columns.extend([
                    'class_offering_code',
                    'year',
                    'semester'
                ])

        # Offer both CSV and Excel formats
        return {
            'type': 'ir.actions.act_window',
            'name': _('Download Template'),
            'res_model': 'template.download.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_columns': columns,
                'default_import_type': import_type,
                'default_is_arabic': is_arabic,
            }
        }

    def action_import(self):
        self.ensure_one()

        if not self.import_file:
            raise UserError(_('Please upload a file to import.'))

        try:
            file_content = self._get_import_file_bytes()
        except Exception as e:
            raise UserError(_('Error reading file: %s') % str(e))

        file_name = self.file_name or 'uploaded_file'
        
        if file_name.lower().endswith(('.xlsx', '.xls')):
            rows_data = self._read_excel_file(file_content)
        else:
            rows_data = self._read_csv_file(file_content)

        rows = []
        errors = []
        
        for row_num, row in enumerate(rows_data, 2):
            if not any(str(v).strip() for v in row.values()):
                continue

            try:
                cleaned_row = {}
                for key, value in row.items():
                    if value is None:
                        cleaned_row[key] = ''
                    else:
                        cleaned_row[key] = str(value).strip()
                
                mapped_row = self._map_csv_row(cleaned_row)
                
                self._validate_required_fields(mapped_row, row_num)
                self._validate_student_row(mapped_row, row_num)
                
                if self.import_type == 'both':
                    self._validate_enrolment_row(mapped_row, row_num)
                    
                self._check_duplicate_national_id(mapped_row, row_num, rows)
                self._check_duplicate_university_id(mapped_row, row_num, rows)
                    
                rows.append((row_num, mapped_row))
            except ValidationError as e:
                errors.append(str(e))
            except Exception as e:
                errors.append(_('Row %(row_num)d: Unexpected error - %(error)s') % {
                    'row_num': row_num,
                    'error': str(e)
                })

        if errors:
            self.write({
                'total_rows': len(rows),
                'imported_students': 0,
                'imported_enrolments': 0,
                'skipped_enrolments': 0,
                'error_count': len(errors),
                'error_log': '\n'.join(errors),
                'state': 'error',
            })
            raise UserError(_('Validation failed. Please fix all errors before importing:\n\n') + '\n'.join(errors))

        imported_students = 0
        imported_enrolments = 0
        skipped_enrolments = 0
        import_warnings = []
        import_errors = []

        try:
            with self.env.cr.savepoint():
                
                # المعالجة المجمعة لجميع الطلاب هنا (سريعة جداً ولا تستهلك الموارد)
                students_dict = self._bulk_process_students(rows)
                
                # حساب عدد الطلاب المضافين/المعدلين بناءً على الأرقام الوطنية الفريدة في الملف
                imported_students = len(set([r[1].get('national_id') for r in rows if r[1].get('national_id')]))

                # معالجة التسجيلات إذا كان النوع 'both'
                if self.import_type == 'both':
                    for row_num, mapped_row in rows:
                        try:
                            nid = mapped_row.get('national_id')
                            student = students_dict.get(nid)
                            
                            if student:
                                enrolment = self._process_enrolment_row(mapped_row, row_num, student)
                                if enrolment == 'skipped':
                                    skipped_enrolments += 1
                                    import_warnings.append(_('Row %(row_num)d: Student is already enrolled in class "%(class_code)s" - Skipped') % {
                                        'row_num': row_num,
                                        'class_code': mapped_row.get('class_offering_code')
                                    })
                                elif enrolment:
                                    imported_enrolments += 1
                                    
                        except Exception as e:
                            import_errors.append(_('Row %(row_num)d: %(error)s') % {
                                'row_num': row_num,
                                'error': str(e)
                            })
                            raise
                
        except Exception as e:
            _logger.error("Import failed, rolling back all changes: %s", str(e))
            
            all_errors = errors + import_errors
            
            self.write({
                'total_rows': len(rows),
                'imported_students': 0,
                'imported_enrolments': 0,
                'skipped_enrolments': 0,
                'error_count': len(all_errors),
                'error_log': '\n'.join(import_warnings + all_errors) if (import_warnings or all_errors) else '',
                'state': 'error',
            })
            
            return {
                'type': 'ir.actions.act_window',
                'res_model': self._name,
                'res_id': self.id,
                'view_mode': 'form',
                'target': 'new',
            }

        all_errors = errors + import_errors
        
        self.write({
            'total_rows': len(rows),
            'imported_students': imported_students,
            'imported_enrolments': imported_enrolments,
            'skipped_enrolments': skipped_enrolments,
            'error_count': len(all_errors),
            'error_log': '\n'.join(import_warnings + all_errors) if (import_warnings or all_errors) else '',
            'state': 'error' if all_errors else 'imported',
        })

        if import_warnings and not import_errors:
            return {
                'type': 'ir.actions.act_window',
                'res_model': self._name,
                'res_id': self.id,
                'view_mode': 'form',
                'target': 'new',
            }

        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'res_id': self.id,
            'view_mode': 'form',
            'target': 'new',
        }

    def _validate_required_fields(self, row, row_num):
        required_fields = ['national_id', 'name', 'email', 'phone', 'date_of_birth']
        
        if self.import_type == 'both':
            required_fields.append('class_offering_code')
        
        for field in required_fields:
            if not row.get(field, '').strip():
                raise ValidationError(_('Row %(row_num)d: %(field)s is required') % {
                    'row_num': row_num,
                    'field': self._get_field_display_name(field)
                })

    def _get_field_display_name(self, field_name):
        display_names = {
            'national_id': 'الرقم الوطني',
            'name': 'الاسم',
            'email': 'البريد الإلكتروني',
            'phone': 'الهاتف',
            'date_of_birth': 'تاريخ الميلاد',
            'university_id': 'رقم الطالب',
            'country_code': 'كود الدولة',
            'class_offering_code': 'رمز البرنامج المقدم',
            'year': 'السنة',
            'semester': 'الفصل'
        }
        return display_names.get(field_name, field_name)

    def _validate_student_row(self, row, row_num):
        nid = row.get('national_id', '').strip()
        phone = row.get('phone', '').strip()
        email = row.get('email', '').strip()
        dob = row.get('date_of_birth', '').strip()
        university_id = row.get('university_id', '').strip()
        country_code = row.get('country_code', '').strip() or 'JO'

        if not nid or len(nid) != 10 or not nid.isdigit():
            raise ValidationError(_('Row %(row_num)d: national_id must be exactly 10 digits') % {'row_num': row_num})

        if not phone or len(phone) != 9 or not phone.isdigit():
            raise ValidationError(_('Row %(row_num)d: phone must be exactly 9 digits') % {'row_num': row_num})

        if not email or '@' not in email:
            raise ValidationError(_('Row %(row_num)d: invalid email') % {'row_num': row_num})

        dob_valid = False
        for fmt in ['%d-%m-%Y', '%Y-%m-%d', '%d/%m/%Y', '%Y/%m/%d']:
            try:
                datetime.strptime(dob, fmt)
                dob_valid = True
                break
            except ValueError:
                continue
        
        if not dob_valid:
            raise ValidationError(_('Row %(row_num)d: date_of_birth must be in format DD-MM-YYYY, YYYY-MM-DD, DD/MM/YYYY, or YYYY/MM/DD') % {'row_num': row_num})

        if university_id and university_id != 'N/A':
            existing_student_by_university_id = self.env['res.partner'].search([
                ('university_id', '=', university_id),
                ('university_id', '!=', 'N/A'),
                ('edu_type', '=', 'student')
            ], limit=1)

            if existing_student_by_university_id:
                existing_nid = existing_student_by_university_id.national_id
                if existing_nid != nid:
                    raise ValidationError(_('Row %(row_num)d: university_id "%(university_id)s" already exists for student with national_id "%(existing_nid)s"') % {
                        'row_num': row_num,
                        'university_id': university_id,
                        'existing_nid': existing_nid
                    })

        country = self.env['res.country'].search([('code', '=', country_code)], limit=1)
        if not country:
            raise ValidationError(_('Row %(row_num)d: Invalid country code "%(country_code)s"') % {
                'row_num': row_num,
                'country_code': country_code
            })

    def _check_duplicate_national_id(self, row, row_num, existing_rows):
        current_nid = row.get('national_id', '').strip()
        
        for existing_row_num, existing_row in existing_rows:
            existing_nid = existing_row.get('national_id', '').strip()
            if current_nid == existing_nid:
                raise ValidationError(_('Row %(row_num)d: Duplicate national_id "%(current_nid)s" (also found in row %(existing_row_num)d)') % {
                    'row_num': row_num,
                    'current_nid': current_nid,
                    'existing_row_num': existing_row_num
                })

    def _check_duplicate_university_id(self, row, row_num, existing_rows):
        current_university_id = row.get('university_id', '').strip()
        
        if not current_university_id or current_university_id == 'N/A':
            return
        
        for existing_row_num, existing_row in existing_rows:
            existing_university_id = existing_row.get('university_id', '').strip()
            if current_university_id == existing_university_id:
                raise ValidationError(_('Row %(row_num)d: Duplicate university_id "%(current_university_id)s" (also found in row %(existing_row_num)d)') % {
                    'row_num': row_num,
                    'current_university_id': current_university_id,
                    'existing_row_num': existing_row_num
                })

    def _validate_year_semester_dates(self, offering, year, semester, row_num, code):
        if not hasattr(offering, 'start_date') or not hasattr(offering, 'end_date'):
            return
        
        if not offering.start_date or not offering.end_date:
            return
        
        start_date = offering.start_date
        end_date = offering.end_date
        
        if isinstance(start_date, date) and not isinstance(start_date, datetime):
            start_date = datetime.combine(start_date, datetime.min.time())
        if isinstance(end_date, date) and not isinstance(end_date, datetime):
            end_date = datetime.combine(end_date, datetime.min.time())
        
        offering_year = start_date.year
        
        try:
            input_year = int(year)
        except (ValueError, TypeError):
            raise ValidationError(_('Row %(row_num)d: Invalid year format "%(year)s"') % {
                'row_num': row_num,
                'year': year
            })
        
        if input_year != offering_year:
            raise ValidationError(_('Row %(row_num)d: The offering "%(code)s" (%(start_date)s - %(end_date)s) is not in the specified year %(input_year)d (offering year: %(offering_year)d)') % {
                'row_num': row_num,
                'code': code,
                'start_date': start_date.strftime('%d/%m/%Y'),
                'end_date': end_date.strftime('%d/%m/%Y'),
                'input_year': input_year,
                'offering_year': offering_year
            })
        
        semester_allowed_months = {
            'first': {9, 10, 11, 12, 1},
            'second': {1, 2, 3, 4, 5, 6},
            'summer': {6, 7, 8},
        }

        if semester not in semester_allowed_months:
            return

        allowed_months = semester_allowed_months[semester]
        offering_start_month = start_date.month

        valid_semester = (offering_start_month in allowed_months)
        
        if not valid_semester:
            semester_names = {
                'first': _('First Semester (September–January)'),
                'second': _('Second Semester (January–June)'),
                'summer': _('Summer Semester (June–August)'),
            }

            raise ValidationError(_(
                'Row %(row_num)d: The offering "%(code)s" '
                '(%(start_date)s - %(end_date)s) '
                'does not fall within the specified semester %(semester_name)s'
            ) % {
                'row_num': row_num,
                'code': code,
                'start_date': start_date.strftime('%d/%m/%Y'),
                'end_date': end_date.strftime('%d/%m/%Y'),
                'semester_name': semester_names.get(semester, semester),
            })

    def _validate_enrolment_row(self, row, row_num):
        code = row.get('class_offering_code', '').strip()
        if not code:
            raise ValidationError(_('Row %(row_num)d: class_offering_code is required') % {'row_num': row_num})

        offering = self.env['academy.program.offering'].search(
            [('sequence_number', '=', code)], limit=1
        )
        if not offering:
            raise ValidationError(_('Row %(row_num)d: Class offering with code "%(code)s" not found') % {
                'row_num': row_num,
                'code': code
            })

        program_type = offering.program_id.program_type if hasattr(offering, 'program_id') and hasattr(offering.program_id, 'program_type') else None
        
        if hasattr(offering, 'state'):
            active_states = ['confirmed', 'active', 'open', 'running', 'in_progress', 'draft']
            allowed_states = active_states + ['pending'] if program_type == 'diploma' else active_states
            
            # Note: The original code had a small typo 'allowed_statuses' vs 'allowed_states'
            if offering.state not in allowed_states:
                status_label = dict(offering._fields['state'].selection).get(offering.state)
                raise ValidationError(_(
                    'Row %(row_num)d: Class offering "%(code)s" is not in an allowed status (status: %(status)s)'
                ) % {
                    'row_num': row_num,
                    'code': code,
                    'status': status_label
                })
            
        elif hasattr(offering, 'status'):
            active_statuses = ['confirmed', 'active', 'open', 'running', 'in_progress', 'draft']
            allowed_statuses = active_statuses + ['pending'] if program_type == 'diploma' else active_statuses
                
            if offering.status not in allowed_statuses:
                raise ValidationError(_('Row %(row_num)d: Class offering "%(code)s" is not in an allowed status (status: %(status)s)') % {
                    'row_num': row_num,
                    'code': code,
                    'status': offering.status
                })

        if hasattr(offering, 'seats_available'):
            if offering.seats_available <= 0:
                raise ValidationError(_('Row %(row_num)d: No seats available in class offering "%(code)s"') % {
                    'row_num': row_num,
                    'code': code
                })

        if program_type == 'diploma':
            year = row.get('year', '').strip()
            semester = row.get('semester', '').strip()
            
            if not year:
                raise ValidationError(_('Row %(row_num)d: year is required for diploma programs') % {'row_num': row_num})
            if not semester:
                raise ValidationError(_('Row %(row_num)d: semester is required for diploma programs') % {'row_num': row_num})
            
            # التعديل المطلوب: دعم كافة صيغ الإدخال العربية
            semester_clean = semester.strip()
            valid_semesters = ['first', 'second', 'summer', '1', '2', '3']
            
            arabic_semesters = {
                'الاول': 'first',
                'الأول': 'first',
                'اول': 'first',
                'أول': 'first',
                'الثاني': 'second',
                'ثاني': 'second',
                'الصيفي': 'summer',
                'صيفي': 'summer',
                'صيفية': 'summer',
                'الصيفية': 'summer'
            }
            
            if semester_clean.lower() in valid_semesters:
                row['semester'] = semester_clean.lower()
            elif semester_clean in arabic_semesters:
                row['semester'] = arabic_semesters[semester_clean]
            else:
                raise ValidationError(_('Row %(row_num)d: semester must be one of: %(semesters)s') % {
                    'row_num': row_num,
                    'semesters': ', '.join(['الاول', 'الثاني', 'صيفي', 'first', 'second', 'summer'])
                })
            
            self._validate_year_semester_dates(offering, year, row['semester'], row_num, code)

    def _bulk_process_students(self, valid_rows):
        """
        المعالجة المجمعة: أسرع طريقة للتعامل مع قاعدة البيانات وتطبيق منطق الرقم الجامعي
        """
        # 1. تجميع الأرقام الوطنية وأكواد الدول بدون تكرار
        national_ids = list(set([row[1].get('national_id') for row in valid_rows if row[1].get('national_id')]))
        country_codes = list(set([row[1].get('country_code', 'JO').strip() or 'JO' for row in valid_rows]))

        # 2. استعلام واحد لقاعدة البيانات (Bulk Search)
        existing_students = self.env['res.partner'].search([
            ('national_id', 'in', national_ids),
            ('edu_type', '=', 'student')
        ])
        countries = self.env['res.country'].search([('code', 'in', country_codes)])

        # 3. تخزين النتائج في قواميس للبحث السريع في الذاكرة
        students_dict = {student.national_id: student for student in existing_students}
        countries_dict = {country.code: country for country in countries}

        new_students_vals = []
        processed_new_nids = set()
        
        invoice_template = self.env.ref('jucct.enrollment_invoice_report', raise_if_not_found=False)

        # 4. تجهيز البيانات
        for row_num, mapped_row in valid_rows:
            nid = mapped_row.get('national_id')
            university_id_from_file = mapped_row.get('university_id', '').strip() or 'N/A'
            c_code = mapped_row.get('country_code', '').strip() or 'JO'
            country = countries_dict.get(c_code)

            date_of_birth = mapped_row.get('date_of_birth', '').strip()
            dob_date = None
            for fmt in ['%d-%m-%Y', '%Y-%m-%d', '%d/%m/%Y', '%Y/%m/%d']:
                try:
                    dob_date = datetime.strptime(date_of_birth, fmt).date()
                    break
                except ValueError:
                    continue

            vals = {
                'national_id': nid,
                'name': mapped_row.get('name', '').strip(),
                'email': mapped_row.get('email', '').strip(),
                'phone': mapped_row.get('phone', '').strip(),
                'date_of_birth': dob_date,
                'edu_type': 'student',
                'country_id': country.id if country else False,
                'country_phone_code': '+' + str(country.phone_code) if country and country.phone_code else '+962',
            }
            if invoice_template:
                vals['invoice_template_pdf_report_id'] = invoice_template.id

            if nid in students_dict:
                existing_student = students_dict[nid]
                
                # تحديث الرقم الجامعي فقط إذا كان فارغاً أو N/A
                if not existing_student.university_id or existing_student.university_id == 'N/A':
                    vals['university_id'] = university_id_from_file
                    
                existing_student.write(vals)
            else:
                if nid not in processed_new_nids:
                    vals['university_id'] = university_id_from_file
                    new_students_vals.append(vals)
                    processed_new_nids.add(nid)

        # 5. إنشاء الطلاب الجدد دفعة واحدة
        if new_students_vals:
            created_students = self.env['res.partner'].create(new_students_vals)
            for student in created_students:
                students_dict[student.national_id] = student

        return students_dict

    def _process_enrolment_row(self, row, row_num, student):
        code = row.get('class_offering_code', '').strip() 
        offering = self.env['academy.program.offering'].search(
            [('sequence_number', '=', code)], limit=1
        )

        existing_enrolment = self.env['sale.order'].search([
            ('partner_id', '=', student.id),
            ('is_enrolment', '=', True),
            ('state', 'in', ['sale', 'done']),
            ('order_line.class_offering_id', '=', offering.id)
        ])
        
        if existing_enrolment:
            return 'skipped'

        order = self.env['sale.order'].create({
            'partner_id': student.id,
            'is_enrolment': True,
            'program_type': offering.program_id.program_type,
            'payment_term_id': self.env.ref('jucct.payment_term_10_percent_monthly').id,
        })

        line_vals = {
            'order_id': order.id,
            'product_id': offering.program_id.product_variant_id.id,
            'product_template_id': offering.program_id.id,
            'program_id': offering.program_id.id,
            'academy_id': offering.academy_id.id,
            'class_offering_id': offering.id,
            'product_uom_qty': 1,
            'price_unit': offering.price,
        }
        
        if offering.program_id.program_type == 'diploma':
            line_vals['year'] = row.get('year', '').strip()
            line_vals['semester'] = row.get('semester', '').strip()
        
        self.env['sale.order.line'].create(line_vals)

        order.with_context(bypass_conflict_check=True).action_confirm()
        return order

    def action_clear_results(self):
        self.write({
            'import_file': False,
            'file_name': False,
            'imported_students': 0,
            'imported_enrolments': 0,
            'skipped_enrolments': 0,
            'error_count': 0,
            'error_log': '',
            'state': 'draft',
        })
        return {
            'type': 'ir.actions.act_window',
            'res_model': self._name,
            'view_mode': 'form',
            'target': 'new',
            'res_id': self.id,
            'context': self.env.context,
        }


# إضافة الـ Wizard للتحميل
class TemplateDownloadWizard(models.TransientModel):
    _name = 'template.download.wizard'
    _description = 'Template Download Options'
    
    file_format = fields.Selection([
        ('csv', 'CSV File'),
        ('xlsx', 'Excel File')
    ], string=_('File Format'), default='xlsx', required=True)
    
    columns = fields.Text(string=_('Columns'), readonly=True)
    import_type = fields.Char(string=_('Import Type'), readonly=True)
    is_arabic = fields.Boolean(string=_('Is Arabic'), readonly=True)
    
    def action_download(self):
        """Download template in selected format"""
        self.ensure_one()
        
        # Parse columns from text
        columns = eval(self.columns) if isinstance(self.columns, str) else self.columns
        
        if self.file_format == 'xlsx':
            return self._download_excel_template(columns)
        else:
            return self._download_csv_template(columns)
    
    def _download_excel_template(self, columns):
        """Create Excel (XLSX) template using xlsxwriter"""
        if XLSXWRITER_SUPPORT:
            try:
                return self._download_excel_template_xlsxwriter(columns)
            except Exception as e:
                _logger.warning("xlsxwriter failed, falling back to openpyxl: %s", str(e))
        
        if EXCEL_SUPPORT:
            return self._download_excel_template_openpyxl(columns)
        else:
            raise UserError(_('Excel export is not available. Please install openpyxl or xlsxwriter.'))

    def _download_excel_template_xlsxwriter(self, columns):
        """Create Excel template using xlsxwriter (more reliable)"""
        import xlsxwriter
        buffer = BytesIO()
        workbook = xlsxwriter.Workbook(buffer, {
            'in_memory': True,
            'default_date_format': 'dd-mm-yyyy',
            'remove_timezone': True,
        })
        worksheet = workbook.add_worksheet('Data')
        for col_idx, col_name in enumerate(columns):
            worksheet.write(0, col_idx, str(col_name))
        
        workbook.close()
        buffer.seek(0)
        file_bytes = buffer.getvalue()
        
        import_type = self.import_type or 'both'
        file_name = f'student_import_template_{import_type}.xlsx'
        attachment = self.env['ir.attachment'].create({
            'name': file_name,
            'raw': file_bytes,
            'type': 'binary',
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }

    def _download_excel_template_openpyxl(self, columns):
        """Create Excel template using openpyxl (fallback)"""
        from openpyxl import Workbook
        wb = Workbook()
        if 'Sheet' in wb.sheetnames:
            std = wb['Sheet']
            wb.remove(std)
        
        ws = wb.create_sheet(title='Data')
        for col_idx, col_name in enumerate(columns, start=1):
            ws.cell(row=1, column=col_idx, value=str(col_name))
        
        buffer = BytesIO()
        wb.save(buffer)
        buffer.seek(0)
        
        import_type = self.import_type or 'both'
        file_name = f'student_import_template_{import_type}.xlsx'
        attachment = self.env['ir.attachment'].create({
            'name': file_name,
            'raw': buffer.getvalue(),
            'type': 'binary',
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })
        return {
            'type': 'ir.actions.act_url',
            'url': f'/web/content/{attachment.id}?download=true',
            'target': 'self',
        }