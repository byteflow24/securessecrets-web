from flask_wtf import FlaskForm
from wtforms import StringField, SubmitField, PasswordField, FileField, TextAreaField, SelectField, EmailField, DateField, BooleanField, DateTimeField, HiddenField
from wtforms.validators import DataRequired, Optional, Length, Regexp, Email, AnyOf



# WTForm for creating a secret
class SecretForm(FlaskForm):
    title = StringField("Title", validators=[DataRequired()], render_kw={"placeholder": "Write a title..."})
    secret = TextAreaField("Keep Your Secret Here", validators=[DataRequired()], render_kw={"placeholder": "Write your secret here!", "rows": 5})
    file = FileField("Upload File e.g. pdf, png, xls (Optional)", validators=[Optional()], render_kw={"class": "form-control", "style": "width: 400px;"})
    submit = SubmitField("Save")


# Regular expression for password complexity
password_regex = r'^(?=.*[A-Z])(?=.*\d)(?=.*\W)(?=.*[a-z]).{8,}$'

# Create a form to register new users
class RegisterForm(FlaskForm):
    email = EmailField("Email", validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired(),
        Regexp(
            regex=password_regex,
            message=(
                "Password must be at least 8 characters long, "
                "contain at least one uppercase letter, one number, and one symbol."
            )
        )
    ])
    confirm_password = PasswordField("Confirm Password", validators=[DataRequired()])
    username = StringField("Username", validators=[DataRequired()])
    code = SelectField("Country Code", 
                       validators=[DataRequired(), 
                                   AnyOf(values=['+1', '+44', '+91', '+61', '+81', '+971', '+966', '+965', 
                                                 '+973', '+968', '+974', '+20', '+962', '+961', '+60', 
                                                 '+63', '+852', '+86', '+55', '+7', '+27', '+34', 
                                                 '+33', '+49', '+39', '+82', '+46', '+31', '+47', 
                                                 '+64', '+41', '+62', '+90', '+66', '+65', '+93', 
                                                 '+355', '+213', '+376', '+244', '+54', '+374', 
                                                 '+43', '+994', '+880', '+375', '+32', '+501', 
                                                 '+229', '+975', '+591', '+387', '+267', '+359', 
                                                 '+226', '+95', '+855', '+237', '+56', '+57', 
                                                 '+506', '+385', '+357', '+420', '+45', '+372', 
                                                 '+358', '+241', '+995', '+30', '+36', '+98', 
                                                 '+353', '+972', '+254', '+856', '+370', '+352', 
                                                 '+389', '+52', '+234', '+92', '+507', '+48', 
                                                 '+351', '+963', '+886', '+58', '+84'])],
                       choices=[
                ('+1', 'US (+1)'), ('+44', 'UK (+44)'), ('+91', 'India (+91)'), ('+61', 'Australia (+61)'), 
                ('+81', 'Japan (+81)'), ('+971', 'United Arab Emirates (+971)'), ('+966', 'Saudi Arabia (+966)'),
                ('+965', 'Kuwait (+965)'), ('+973', 'Bahrain (+973)'), ('+968', 'Oman (+968)'), ('+974', 'Qatar (+974)'), 
                ('+20', 'Egypt (+20)'), ('+962', 'Jordan (+962)'), ('+961', 'Lebanon (+961)'), 
                ('+60', 'Malaysia (+60)'), ('+63', 'Philippines (+63)'), ('+852', 'Hong Kong (+852)'), ('+86', 'China (+86)'), 
                ('+55', 'Brazil (+55)'), ('+7', 'Russia (+7)'), ('+27', 'South Africa (+27)'), ('+34', 'Spain (+34)'), 
                ('+33', 'France (+33)'), ('+49', 'Germany (+49)'), ('+39', 'Italy (+39)'), ('+82', 'South Korea (+82)'), 
                ('+46', 'Sweden (+46)'), ('+31', 'Netherlands (+31)'), ('+47', 'Norway (+47)'), ('+64', 'New Zealand (+64)'), 
                ('+41', 'Switzerland (+41)'), ('+62', 'Indonesia (+62)'), ('+90', 'Turkey (+90)'), ('+66', 'Thailand (+66)'), 
                ('+65', 'Singapore (+65)'), ('+93', 'Afghanistan (+93)'), ('+355', 'Albania (+355)'), ('+213', 'Algeria (+213)'), 
                ('+376', 'Andorra (+376)'), ('+244', 'Angola (+244)'), ('+54', 'Argentina (+54)'), ('+374', 'Armenia (+374)'), 
                ('+43', 'Austria (+43)'), ('+994', 'Azerbaijan (+994)'), ('+880', 'Bangladesh (+880)'), 
                ('+375', 'Belarus (+375)'), ('+32', 'Belgium (+32)'), ('+501', 'Belize (+501)'), ('+229', 'Benin (+229)'), 
                ('+975', 'Bhutan (+975)'), ('+591', 'Bolivia (+591)'), ('+387', 'Bosnia and Herzegovina (+387)'), 
                ('+267', 'Botswana (+267)'), ('+359', 'Bulgaria (+359)'), ('+226', 'Burkina Faso (+226)'), ('+95', 'Myanmar (+95)'), 
                ('+855', 'Cambodia (+855)'), ('+237', 'Cameroon (+237)'), ('+1', 'Canada (+1)'), ('+56', 'Chile (+56)'), 
                ('+57', 'Colombia (+57)'), ('+506', 'Costa Rica (+506)'), ('+385', 'Croatia (+385)'), 
                ('+357', 'Cyprus (+357)'), ('+420', 'Czech Republic (+420)'), ('+45', 'Denmark (+45)')])
    phone = StringField("Phone Number", validators=[DataRequired(), Regexp(r'^\d{8,10}$', message="Phone number must be between 8 and 10 digits and contain only numbers.")])
    confirm_conditions = BooleanField("", validators=[DataRequired()])
    submit = SubmitField("Sign Me Up!")

# ProfileForm
class ProfileForm(FlaskForm):
    email = StringField("Email", validators=[DataRequired()])
    username = StringField("Username", validators=[DataRequired()])
    code = SelectField("Country Code", 
                       validators=[DataRequired()],
                       choices=[
                ('+1', 'US (+1)'), ('+44', 'UK (+44)'), ('+91', 'India (+91)'), ('+61', 'Australia (+61)'), 
                ('+81', 'Japan (+81)'), ('+971', 'United Arab Emirates (+971)'), ('+966', 'Saudi Arabia (+966)'),
                ('+965', 'Kuwait (+965)'), ('+973', 'Bahrain (+973)'), ('+968', 'Oman (+968)'), ('+974', 'Qatar (+974)'), 
                ('+20', 'Egypt (+20)'), ('+962', 'Jordan (+962)'), ('+961', 'Lebanon (+961)'), 
                ('+60', 'Malaysia (+60)'), ('+63', 'Philippines (+63)'), ('+852', 'Hong Kong (+852)'), ('+86', 'China (+86)'), 
                ('+55', 'Brazil (+55)'), ('+7', 'Russia (+7)'), ('+27', 'South Africa (+27)'), ('+34', 'Spain (+34)'), 
                ('+33', 'France (+33)'), ('+49', 'Germany (+49)'), ('+39', 'Italy (+39)'), ('+82', 'South Korea (+82)'), 
                ('+46', 'Sweden (+46)'), ('+31', 'Netherlands (+31)'), ('+47', 'Norway (+47)'), ('+64', 'New Zealand (+64)'), 
                ('+41', 'Switzerland (+41)'), ('+62', 'Indonesia (+62)'), ('+90', 'Turkey (+90)'), ('+66', 'Thailand (+66)'), 
                ('+65', 'Singapore (+65)'), ('+93', 'Afghanistan (+93)'), ('+355', 'Albania (+355)'), ('+213', 'Algeria (+213)'), 
                ('+376', 'Andorra (+376)'), ('+244', 'Angola (+244)'), ('+54', 'Argentina (+54)'), ('+374', 'Armenia (+374)'), 
                ('+43', 'Austria (+43)'), ('+994', 'Azerbaijan (+994)'), ('+880', 'Bangladesh (+880)'), 
                ('+375', 'Belarus (+375)'), ('+32', 'Belgium (+32)'), ('+501', 'Belize (+501)'), ('+229', 'Benin (+229)'), 
                ('+975', 'Bhutan (+975)'), ('+591', 'Bolivia (+591)'), ('+387', 'Bosnia and Herzegovina (+387)'), 
                ('+267', 'Botswana (+267)'), ('+359', 'Bulgaria (+359)'), ('+226', 'Burkina Faso (+226)'), ('+95', 'Myanmar (+95)'), 
                ('+855', 'Cambodia (+855)'), ('+237', 'Cameroon (+237)'), ('+1', 'Canada (+1)'), ('+56', 'Chile (+56)'), 
                ('+57', 'Colombia (+57)'), ('+506', 'Costa Rica (+506)'), ('+385', 'Croatia (+385)'), 
                ('+357', 'Cyprus (+357)'), ('+420', 'Czech Republic (+420)'), ('+45', 'Denmark (+45)')])
    phone = StringField("Phone Number", validators=[DataRequired(), Regexp(r'^\d+$', message="Phone number must contain only numbers.")])
    submit = SubmitField("Update Profile")

# ChangePasswordForm
class ChangePasswordForm(FlaskForm):
    current_password = PasswordField("Current Password", validators=[DataRequired()])
    new_password = PasswordField("New Password", validators=[DataRequired(),
        Regexp(
            regex=password_regex,
            message=(
                "Password must be at least 8 characters long, "
                "contain at least one uppercase letter, one number, and one symbol."
            )
        )
    ])
    confirm_password = PasswordField("Confirm New Password", validators=[DataRequired()])
    submit = SubmitField("Change Password")


# Create a form to login existing users
class LoginForm(FlaskForm):
    user = StringField("Email/ Username", validators=[DataRequired()], render_kw={'placeholder': 'Email, username'})
    password = PasswordField("Password", validators=[DataRequired()], render_kw={'placeholder': 'Password'})
    submit = SubmitField("Let Me In!")

# Forget password
class ForgetPaswdForm(FlaskForm):
    new_password = PasswordField("New Password", validators=[DataRequired()])
    confirm_password = PasswordField("Confirm New Password", validators=[DataRequired()])
    submit = SubmitField("Change Password")

# Search option
class SearchForm(FlaskForm):
    search = StringField("Search", validators=[Optional()],
        render_kw={"placeholder": "Search secrets...", "class": "form-control", "aria-label": "Search secrets"})
    date_filter = SelectField( "Date", choices=[('latest', 'Latest'), ('oldest', 'Oldest')], default='latest',
        render_kw={"class": "form-select", "aria-label": "Filter by date"})
    alpha_filter = SelectField( "Alphabetical", validators=[Optional()], choices=[('A-Z', 'A-Z'), ('Z-A', 'Z-A')], default='A-Z',
        render_kw={"class": "form-select", "aria-label": "Filter alphabetically"})
    submit = SubmitField("Filter",render_kw={"class": "btn btn-primary w-100"})

# Sharing the secret to some one
class ShareForm(FlaskForm):
    email = EmailField(
        "Email",
        validators=[DataRequired(), Email()],
        render_kw={"placeholder": "Email", "class": "form-control"}
    )
    date = DateField(
        "When should the secret be sent?",
        validators=[Optional()],
        render_kw={"class": "form-control", "style": "display:none;"}  # Initially hidden
    )
    time = DateTimeField("",format='%H:%M', validators=[Optional()], render_kw={"class": "form-control", "type": "time", "style": "display:none;"})
    
    confirm_deletion = BooleanField(
        "I want the link to be deleted 1 hour after it is opened.", validators=[Optional()]
    )
    submit = SubmitField("Send", render_kw={"class": "btn btn-primary w-50"})

# Deleting account
class DeleteAccountForm(FlaskForm):
    confirm_delete = HiddenField('confirm_delete', validators=[DataRequired()])


# Upgrading plan
class PlanUpgradeForm(FlaskForm):
    plan_id = SelectField('Choose a Plan:', coerce=int)
    submit = SubmitField('Upgrade Now')
    
# Payment Form
class CardDetailsForm(FlaskForm):
    card_number = StringField("Card Number", validators=[
        DataRequired(),
        Regexp(r'^\d{16}$', message="Card number must be 16 digits.")
    ])
    exp_date = StringField("Expiration Date", validators=[
        DataRequired(),
        Regexp(r'^(0[1-9]|1[0-2])\/?([0-9]{2})$', message="Expiration date must be in MM/YY format.")
    ])
    cvc = StringField("CVC", validators=[
        DataRequired(),
        Regexp(r'^\d{3,4}$', message="CVC must be 3 or 4 digits.")
    ])
    name = StringField("Name on Card", validators=[
        DataRequired(),
        Length(min=1, max=100, message="Name on card must be between 1 and 100 characters.")
    ])
    submit = SubmitField("Pay")

